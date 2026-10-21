from pathlib import Path

import numpy as np
import yaml
from fastapi.testclient import TestClient

from mlops_platform.api import create_app
from mlops_platform.kafka_events import PredictionEvent
from mlops_platform.serving import ModelBundle, ModelIdentity


class FakeModel:
    def predict_proba(self, frame):
        probability = 0.8 if float(frame.iloc[0, 0]) > 0 else 0.2
        return np.array([[1.0 - probability, probability]])


def _write_config(tmp_path: Path) -> Path:
    config = {
        "dataset": {"n_features": 2},
        "registry": {
            "model_name": "demo-model",
            "champion_alias": "champion",
        },
        "serving": {
            "model_alias": "champion",
            "probability_threshold": 0.5,
        },
    }
    path = tmp_path / "train.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def _fake_loader(_: Path) -> ModelBundle:
    return ModelBundle(
        model=FakeModel(),
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


def test_health_ready_info_and_prediction(tmp_path: Path) -> None:
    app = create_app(_write_config(tmp_path), loader=_fake_loader)

    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"

        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["model_version"] == "7"

        info = client.get("/v1/model-info")
        assert info.status_code == 200
        assert info.json()["model_uri"] == "models:/demo-model@champion"

        response = client.post(
            "/v1/predict",
            json={"features": {"feature_00": 1.0, "feature_01": 2.0}},
        )
        assert response.status_code == 200
        assert response.json()["prediction"] == 1
        assert response.json()["probability"] == 0.8
        assert response.json()["model_alias"] == "champion"


def test_prediction_rejects_wrong_feature_contract(tmp_path: Path) -> None:
    app = create_app(_write_config(tmp_path), loader=_fake_loader)

    with TestClient(app) as client:
        response = client.post(
            "/v1/predict",
            json={"features": {"feature_00": 1.0, "unexpected": 2.0}},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "error": "feature_contract_violation",
        "missing": ["feature_01"],
        "extra": ["unexpected"],
    }


def test_readiness_is_503_when_model_load_fails(tmp_path: Path) -> None:
    def failing_loader(_: Path) -> ModelBundle:
        raise RuntimeError("registry unavailable")

    app = create_app(_write_config(tmp_path), loader=failing_loader)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        ready = client.get("/ready")
        prediction = client.post(
            "/v1/predict",
            json={"features": {"feature_00": 1.0, "feature_01": 2.0}},
        )

    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready", "reason": "model_unavailable"}
    assert prediction.status_code == 503


def test_request_rejects_non_finite_feature_values(tmp_path: Path) -> None:
    app = create_app(_write_config(tmp_path), loader=_fake_loader)

    with TestClient(app) as client:
        response = client.post(
            "/v1/predict",
            json={"features": {"feature_00": "NaN", "feature_01": 2.0}},
        )

    assert response.status_code == 422


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[PredictionEvent] = []
        self.closed = False

    def publish(self, event: PredictionEvent) -> str:
        self.events.append(event)
        return "queued"

    def close(self) -> None:
        self.closed = True


def test_prediction_emits_versioned_event_without_changing_response_contract(
    tmp_path: Path,
) -> None:
    publisher = RecordingPublisher()
    app = create_app(
        _write_config(tmp_path),
        loader=_fake_loader,
        publisher_factory=lambda _: publisher,
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/predict",
            json={"features": {"feature_00": 1.0, "feature_01": 2.0}},
        )

    assert response.status_code == 200
    assert len(publisher.events) == 1
    event = publisher.events[0]
    assert event.request_id == response.json()["request_id"]
    assert event.model_version == "7"
    assert event.features == {"feature_00": 1.0, "feature_01": 2.0}
    assert publisher.closed is True
