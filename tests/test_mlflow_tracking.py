import json
from pathlib import Path

import mlflow
import yaml
from mlflow.tracking import MlflowClient

from mlops_platform.data import DatasetConfig, build_dataframe, write_dataset
from mlops_platform.train import train


def test_training_logs_complete_mlflow_run(tmp_path: Path) -> None:
    db_path = tmp_path / "mlflow.db"
    config = {
        "seed": 42,
        "dataset": {
            "n_samples": 300,
            "n_features": 10,
            "n_informative": 6,
            "n_redundant": 2,
            "class_sep": 1.2,
        },
        "split": {"test_size": 0.25},
        "model": {"C": 1.0, "max_iter": 500},
        "paths": {
            "dataset": str(tmp_path / "dataset.csv"),
            "artifact_dir": str(tmp_path / "artifacts"),
        },
        "mlflow": {
            "enabled": True,
            "tracking_uri": f"sqlite:///{db_path}",
            "experiment_name": "mlops-platform-test",
            "run_name": "pytest-mlflow",
        },
    }
    config_path = tmp_path / "train.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    dataset_config = DatasetConfig(**config["dataset"])
    write_dataset(build_dataframe(dataset_config, seed=42), Path(config["paths"]["dataset"]))

    metrics = train(config_path)
    assert metrics["roc_auc"] > 0.8

    run_info = json.loads((tmp_path / "artifacts" / "mlflow_run.json").read_text(encoding="utf-8"))
    mlflow.set_tracking_uri(config["mlflow"]["tracking_uri"])
    run = MlflowClient().get_run(run_info["run_id"])
    assert set(metrics) <= set(run.data.metrics)
    assert run.data.tags["project"] == "mlops-platform"
    assert len(run.data.tags["dataset.sha256"]) == 64
    assert run.data.params["model_C"] == "1.0"
