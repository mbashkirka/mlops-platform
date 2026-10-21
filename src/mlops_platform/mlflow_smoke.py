"""Validate the latest MLflow run contract for M2."""

from __future__ import annotations

import argparse
from pathlib import Path

import mlflow
from mlflow.tracking import MlflowClient

from mlops_platform.data import load_config
from mlops_platform.tracking import resolve_tracking_uri

REQUIRED_METRICS = {"roc_auc", "accuracy", "f1"}
REQUIRED_PARAMS = {"seed", "test_size", "n_features", "dataset_rows", "model_C"}
REQUIRED_TAGS = {"project", "project.version", "dataset.sha256", "data.contract"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/train.yaml"))
    args = parser.parse_args()

    config = load_config(args.config)
    settings = config["mlflow"]
    mlflow.set_tracking_uri(resolve_tracking_uri(config))
    client = MlflowClient()
    experiment = client.get_experiment_by_name(str(settings["experiment_name"]))
    if experiment is None:
        raise RuntimeError("MLflow experiment does not exist")

    runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        order_by=["attributes.start_time DESC"],
        max_results=1,
    )
    if not runs:
        raise RuntimeError("MLflow experiment has no runs")

    run = runs[0]
    missing_metrics = REQUIRED_METRICS - set(run.data.metrics)
    missing_params = REQUIRED_PARAMS - set(run.data.params)
    missing_tags = REQUIRED_TAGS - set(run.data.tags)
    if missing_metrics or missing_params or missing_tags:
        raise RuntimeError(
            "MLflow run contract failed: "
            f"metrics={sorted(missing_metrics)}, "
            f"params={sorted(missing_params)}, "
            f"tags={sorted(missing_tags)}"
        )
    if len(run.data.tags["dataset.sha256"]) != 64:
        raise RuntimeError("dataset.sha256 tag is not a SHA-256 fingerprint")

    print("MLflow M2 smoke: PASSED")
    print(f"experiment={settings['experiment_name']}")
    print(f"run_id={run.info.run_id}")
    print(f"roc_auc={run.data.metrics['roc_auc']:.6f}")
    print(f"dataset_sha256={run.data.tags['dataset.sha256']}")


if __name__ == "__main__":
    main()
