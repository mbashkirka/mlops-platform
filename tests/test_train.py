import json
from pathlib import Path

import yaml

from mlops_platform.data import DatasetConfig, build_dataframe, write_dataset
from mlops_platform.train import train


def _write_config(tmp_path: Path, *, mlflow_enabled: bool) -> Path:
    config = {
        "seed": 42,
        "dataset": {
            "n_samples": 500,
            "n_features": 12,
            "n_informative": 7,
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
            "enabled": mlflow_enabled,
            "tracking_uri": f"sqlite:///{tmp_path / 'mlflow.db'}",
            "experiment_name": "mlops-platform-test",
            "run_name": "pytest-baseline",
        },
    }
    config_path = tmp_path / "train.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    dataset_config = DatasetConfig(**config["dataset"])
    write_dataset(build_dataframe(dataset_config, seed=42), Path(config["paths"]["dataset"]))
    return config_path


def test_training_creates_lineage_aware_artifacts(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, mlflow_enabled=False)
    metrics = train(config_path)
    assert metrics["roc_auc"] > 0.8

    artifact_dir = tmp_path / "artifacts"
    metadata = json.loads((artifact_dir / "model_meta.json").read_text(encoding="utf-8"))
    assert (artifact_dir / "model.joblib").exists()
    reference_path = artifact_dir / "reference_profile.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    assert reference["profile_version"] == "numeric_psi_v1"
    assert reference["rows"] == 375
    assert len(reference["features"]) == 12
    assert len(metadata["dataset_sha256"]) == 64
    assert len(metadata["model_sha256"]) == 64
    assert metadata["mlflow"] is None
