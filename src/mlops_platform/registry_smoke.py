"""Validate the M3 MLflow Model Registry contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import mlflow
import mlflow.sklearn

from mlops_platform.data import feature_columns, load_config, read_dataset
from mlops_platform.registry import _configure_mlflow
from mlops_platform.tracking import resolve_tracking_uri


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/train.yaml"))
    args = parser.parse_args()

    config = load_config(args.config)
    client = _configure_mlflow(config)
    settings = config["registry"]
    model_name = str(settings["model_name"])
    candidate_alias = str(settings["candidate_alias"])
    champion_alias = str(settings["champion_alias"])

    decision_path = Path(config["paths"]["artifact_dir"]) / "registry_decision.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))

    candidate = client.get_model_version_by_alias(model_name, candidate_alias)
    if str(candidate.version) != str(decision["candidate_version"]):
        raise RuntimeError("candidate alias does not match latest registry decision")

    if decision["promoted"]:
        champion = client.get_model_version_by_alias(model_name, champion_alias)
        if str(champion.version) != str(candidate.version):
            raise RuntimeError("promoted candidate is not the champion")
        if champion.tags.get("validation_status") != "passed":
            raise RuntimeError("champion validation_status is not passed")

        frame = read_dataset(Path(config["paths"]["dataset"]))
        features = feature_columns(int(config["dataset"]["n_features"]))
        tracking_uri = resolve_tracking_uri(config)
        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_registry_uri(tracking_uri)
        model = mlflow.sklearn.load_model(f"models:/{model_name}@{champion_alias}")
        predictions = model.predict_proba(frame.loc[[0], features])
        if predictions.shape != (1, 2):
            raise RuntimeError("registered champion returned an unexpected prediction shape")

    print("MLflow M3 registry smoke: PASSED")
    print(f"model_name={model_name}")
    print(f"candidate_version={candidate.version}")
    print(f"promoted={decision['promoted']}")
    print(f"reason={decision['reason']}")


if __name__ == "__main__":
    main()
