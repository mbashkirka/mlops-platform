"""Inspect recent MLflow experiment runs from the command line."""

from __future__ import annotations

import argparse
from pathlib import Path

import mlflow

from mlops_platform.data import load_config
from mlops_platform.tracking import resolve_tracking_uri


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/train.yaml"))
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    config = load_config(args.config)
    settings = config["mlflow"]
    mlflow.set_tracking_uri(resolve_tracking_uri(config))
    experiment_name = str(settings["experiment_name"])

    runs = mlflow.search_runs(
        experiment_names=[experiment_name],
        max_results=args.limit,
        order_by=["metrics.roc_auc DESC"],
    )
    if runs.empty:
        print(f"No runs found for experiment: {experiment_name}")
        return

    columns = [
        "run_id",
        "status",
        "metrics.roc_auc",
        "metrics.accuracy",
        "metrics.f1",
        "params.model_C",
        "tags.dataset.sha256",
    ]
    available = [column for column in columns if column in runs.columns]
    print(runs[available].to_string(index=False))


if __name__ == "__main__":
    main()
