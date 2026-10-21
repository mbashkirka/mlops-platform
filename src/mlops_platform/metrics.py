"""Prometheus metrics for the online inference service."""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


@dataclass(frozen=True)
class ApiMetrics:
    registry: CollectorRegistry
    requests: Counter
    latency: Histogram
    predictions: Counter
    probability: Histogram
    model_ready: Gauge
    model_info: Gauge
    kafka_publish: Counter


def create_api_metrics() -> ApiMetrics:
    registry = CollectorRegistry()
    return ApiMetrics(
        registry=registry,
        requests=Counter(
            "mlops_http_requests_total",
            "HTTP requests handled by the inference API.",
            ("method", "path", "status"),
            registry=registry,
        ),
        latency=Histogram(
            "mlops_http_request_duration_seconds",
            "Inference API request latency in seconds.",
            ("method", "path"),
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
            registry=registry,
        ),
        predictions=Counter(
            "mlops_predictions_total",
            "Predictions emitted by the champion model.",
            ("prediction",),
            registry=registry,
        ),
        probability=Histogram(
            "mlops_prediction_probability",
            "Positive-class probabilities emitted by the champion model.",
            buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
            registry=registry,
        ),
        model_ready=Gauge(
            "mlops_model_ready",
            "Whether a champion model is loaded and ready for inference.",
            registry=registry,
        ),
        kafka_publish=Counter(
            "mlops_kafka_publish_total",
            "Prediction events handed to the Kafka publisher.",
            ("status",),
            registry=registry,
        ),
        model_info=Gauge(
            "mlops_model_info",
            "Identity of the model currently serving traffic.",
            ("model_name", "alias", "version"),
            registry=registry,
        ),
    )
