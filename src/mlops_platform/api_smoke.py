"""End-to-end M4 smoke test against the configured MLflow champion."""

from __future__ import annotations

import argparse
from pathlib import Path

from fastapi.testclient import TestClient

from mlops_platform.api import create_app
from mlops_platform.data import feature_columns, load_config, read_dataset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/train.yaml"))
    args = parser.parse_args()

    config = load_config(args.config)
    dataset_path = Path(config["paths"]["dataset"])
    frame = read_dataset(dataset_path)
    names = feature_columns(int(config["dataset"]["n_features"]))
    features = {name: float(frame.iloc[0][name]) for name in names}

    with TestClient(create_app(args.config)) as client:
        health = client.get("/health")
        ready = client.get("/ready")
        model_info = client.get("/v1/model-info")
        prediction = client.post("/v1/predict", json={"features": features})

    assert health.status_code == 200, health.text
    assert ready.status_code == 200, ready.text
    assert model_info.status_code == 200, model_info.text
    assert prediction.status_code == 200, prediction.text

    info = model_info.json()
    result = prediction.json()
    expected_alias = str(config.get("serving", {}).get("model_alias", "champion"))
    expected_model = str(config["registry"]["model_name"])

    assert info["alias"] == expected_alias
    assert info["model_name"] == expected_model
    assert info["model_uri"] == f"models:/{expected_model}@{expected_alias}"
    assert result["model_alias"] == expected_alias
    assert result["model_version"] == info["version"]
    assert 0.0 <= float(result["probability"]) <= 1.0

    print("FastAPI M4 smoke: PASSED")
    print(f"model_uri={info['model_uri']}")
    print(f"model_version={info['version']}")
    print(f"run_id={info['run_id']}")
    print(f"probability={float(result['probability']):.6f}")
    print(f"prediction={result['prediction']}")


if __name__ == "__main__":
    main()
