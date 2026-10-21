from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from mlops_platform.api import create_app
from mlops_platform.serving import ModelBundle, ModelIdentity


class MetricsFakeModel:
    def predict_proba(self, frame):
        probability = 0.8 if float(frame.iloc[0, 0]) > 0 else 0.2
        return np.array([[1.0 - probability, probability]])


def _metrics_bundle(_: Path) -> ModelBundle:
    return ModelBundle(
        model=MetricsFakeModel(),
        identity=ModelIdentity(
            model_name="demo-model",
            alias="champion",
            version="7",
            run_id="run-123",
            model_uri="models:/demo-model@champion",
            dataset_sha256="a" * 64,
            roc_auc=0.91,
        ),
        feature_names=("feature_00", "feature_01"),
        probability_threshold=0.5,
    )


def test_metrics_expose_http_prediction_and_model_state() -> None:
    app = create_app(loader=_metrics_bundle)

    with TestClient(app) as client:
        payload = {"features": {"feature_00": 1.0, "feature_01": 0.0}}
        assert client.post("/v1/predict", json=payload).status_code == 200
        assert client.get("/health").status_code == 200
        response = client.get("/metrics")

    assert response.status_code == 200
    body = response.text
    assert "mlops_http_requests_total" in body
    assert 'path="/v1/predict",status="200"' in body
    assert 'mlops_predictions_total{prediction="1"} 1.0' in body
    assert "mlops_prediction_probability_count 1.0" in body
    assert "mlops_model_ready 1.0" in body
    assert 'mlops_kafka_publish_total{status="disabled"} 1.0' in body
    assert 'mlops_model_info{alias="champion",model_name="demo-model",version="7"} 1.0' in body


def test_metrics_report_not_ready_model() -> None:
    def failed_loader(_: Path) -> ModelBundle:
        raise RuntimeError("missing model")

    app = create_app(loader=failed_loader)
    with TestClient(app) as client:
        response = client.get("/metrics")

    assert "mlops_model_ready 0.0" in response.text
