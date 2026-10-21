"""FastAPI application for serving the promoted MLflow champion model."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict, FiniteFloat

from mlops_platform import __version__
from mlops_platform.kafka_events import (
    PredictionEvent,
    PredictionPublisher,
    build_prediction_publisher,
)
from mlops_platform.metrics import ApiMetrics, create_api_metrics
from mlops_platform.serving import ModelBundle, load_champion, predict_probability

LOGGER = logging.getLogger(__name__)
Loader = Callable[[Path], ModelBundle]
PublisherFactory = Callable[[Path], PredictionPublisher]


class PredictRequest(BaseModel):
    """Strict online inference request."""

    model_config = ConfigDict(extra="forbid")
    features: dict[str, FiniteFloat]


class PredictionResponse(BaseModel):
    request_id: str
    prediction: int
    probability: float
    threshold: float
    model_name: str
    model_alias: str
    model_version: str


class HealthResponse(BaseModel):
    status: str
    service: str
    project_version: str


class ReadyResponse(BaseModel):
    status: str
    model_name: str
    model_alias: str
    model_version: str


class ModelInfoResponse(BaseModel):
    model_name: str
    alias: str
    version: str
    run_id: str
    model_uri: str
    dataset_sha256: str
    roc_auc: float | None
    n_features: int
    probability_threshold: float
    project_version: str


def _bundle_or_503(request: Request) -> ModelBundle:
    bundle = getattr(request.app.state, "model_bundle", None)
    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="model_not_ready",
        )
    return bundle


def _validate_feature_contract(bundle: ModelBundle, features: dict[str, float]) -> None:
    expected = set(bundle.feature_names)
    received = set(features)
    if received == expected:
        return

    missing = sorted(expected - received)
    extra = sorted(received - expected)
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": "feature_contract_violation", "missing": missing, "extra": extra},
    )


def _set_model_metrics(metrics: ApiMetrics, bundle: ModelBundle | None) -> None:
    metrics.model_ready.set(0 if bundle is None else 1)
    if bundle is None:
        return
    metrics.model_info.labels(
        model_name=bundle.identity.model_name,
        alias=bundle.identity.alias,
        version=bundle.identity.version,
    ).set(1)


def create_app(
    config_path: Path | None = None,
    loader: Loader = load_champion,
    publisher_factory: PublisherFactory = build_prediction_publisher,
) -> FastAPI:
    """Create an application with an injectable model loader for deterministic tests."""
    resolved_config = config_path or Path(os.getenv("MLOPS_CONFIG", "configs/train.yaml"))
    metrics = create_api_metrics()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.model_bundle = None
        app.state.model_load_error = None
        app.state.prediction_publisher = publisher_factory(resolved_config)
        _set_model_metrics(metrics, None)
        try:
            app.state.model_bundle = loader(resolved_config)
            _set_model_metrics(metrics, app.state.model_bundle)
        except Exception as exc:
            app.state.model_load_error = type(exc).__name__
            LOGGER.exception("Failed to load serving model")
        yield
        app.state.prediction_publisher.close()
        app.state.model_bundle = None
        _set_model_metrics(metrics, None)

    application = FastAPI(
        title="MLOps Platform Inference API",
        version=__version__,
        lifespan=lifespan,
    )
    application.state.metrics = metrics

    @application.middleware("http")
    async def prometheus_middleware(request: Request, call_next):
        started = time.perf_counter()
        response = None
        try:
            response = await call_next(request)
            return response
        finally:
            status_code = 500 if response is None else response.status_code
            labels = {
                "method": request.method,
                "path": request.url.path,
                "status": str(status_code),
            }
            metrics.requests.labels(**labels).inc()
            metrics.latency.labels(
                method=request.method,
                path=request.url.path,
            ).observe(time.perf_counter() - started)

    @application.get("/metrics", include_in_schema=False)
    def prometheus_metrics() -> Response:
        return Response(
            content=generate_latest(metrics.registry),
            media_type=CONTENT_TYPE_LATEST,
        )

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service="mlops-platform", project_version=__version__)

    @application.get(
        "/ready",
        response_model=ReadyResponse,
        responses={503: {"description": "Champion model is not available"}},
    )
    def ready(request: Request):
        bundle = getattr(request.app.state, "model_bundle", None)
        if bundle is None:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready", "reason": "model_unavailable"},
            )
        return ReadyResponse(
            status="ready",
            model_name=bundle.identity.model_name,
            model_alias=bundle.identity.alias,
            model_version=bundle.identity.version,
        )

    @application.get("/v1/model-info", response_model=ModelInfoResponse)
    def model_info(request: Request) -> ModelInfoResponse:
        bundle = _bundle_or_503(request)
        identity = bundle.identity
        return ModelInfoResponse(
            model_name=identity.model_name,
            alias=identity.alias,
            version=identity.version,
            run_id=identity.run_id,
            model_uri=identity.model_uri,
            dataset_sha256=identity.dataset_sha256,
            roc_auc=identity.roc_auc,
            n_features=len(bundle.feature_names),
            probability_threshold=bundle.probability_threshold,
            project_version=__version__,
        )

    @application.post("/v1/predict", response_model=PredictionResponse)
    def predict(payload: PredictRequest, request: Request) -> PredictionResponse:
        bundle = _bundle_or_503(request)
        features = {name: float(value) for name, value in payload.features.items()}
        _validate_feature_contract(bundle, features)
        probability = predict_probability(bundle, features)
        prediction = int(probability >= bundle.probability_threshold)
        request_id = uuid4().hex
        metrics.predictions.labels(prediction=str(prediction)).inc()
        metrics.probability.observe(probability)
        event = PredictionEvent.create(
            request_id=request_id,
            features=features,
            prediction=prediction,
            probability=probability,
            threshold=bundle.probability_threshold,
            model_name=bundle.identity.model_name,
            model_alias=bundle.identity.alias,
            model_version=bundle.identity.version,
            run_id=bundle.identity.run_id,
            dataset_sha256=bundle.identity.dataset_sha256,
        )
        publish_status = request.app.state.prediction_publisher.publish(event)
        metrics.kafka_publish.labels(status=publish_status).inc()
        return PredictionResponse(
            request_id=request_id,
            prediction=prediction,
            probability=probability,
            threshold=bundle.probability_threshold,
            model_name=bundle.identity.model_name,
            model_alias=bundle.identity.alias,
            model_version=bundle.identity.version,
        )

    return application


app = create_app()
