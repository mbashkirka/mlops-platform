from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from airflow.sdk import dag, task

PROJECT_ROOT = Path(os.getenv("MLOPS_AIRFLOW_PROJECT_ROOT", "/opt/airflow/project"))
CONFIG = Path(os.getenv("MLOPS_CONFIG", PROJECT_ROOT / "configs/train.yaml"))
DATASET = PROJECT_ROOT / "data/raw/dataset.csv"
ARTIFACT_DIR = PROJECT_ROOT / "artifacts"


def _run(*args: str) -> None:
    subprocess.run(args, cwd=PROJECT_ROOT, check=True)


@dag(
    dag_id="mlops_training_pipeline",
    schedule=None,
    catchup=False,
    max_active_runs=1,
    tags=["mlops-platform", "training", "registry"],
)
def training_pipeline():
    @task
    def generate_data() -> str:
        _run(
            "python",
            "-m",
            "mlops_platform.data",
            "--config",
            str(CONFIG),
            "--output",
            str(DATASET),
        )
        return str(DATASET)

    @task
    def validate_data() -> str:
        _run(
            "python",
            "-m",
            "mlops_platform.data_validation",
            "--config",
            str(CONFIG),
            "--input",
            str(DATASET),
            "--report",
            str(ARTIFACT_DIR / "data_validation.json"),
            "--manifest",
            str(ARTIFACT_DIR / "data_manifest.json"),
        )
        return str(ARTIFACT_DIR / "data_manifest.json")

    @task
    def train_model() -> str:
        _run(
            "python",
            "-m",
            "mlops_platform.train",
            "--config",
            str(CONFIG),
            "--data",
            str(DATASET),
        )
        return str(ARTIFACT_DIR / "mlflow_run.json")

    @task
    def register_model() -> str:
        _run(
            "python",
            "-m",
            "mlops_platform.registry",
            "--config",
            str(CONFIG),
        )
        return str(ARTIFACT_DIR / "registry_decision.json")

    @task
    def registry_smoke() -> dict[str, object]:
        _run(
            "python",
            "-m",
            "mlops_platform.registry_smoke",
            "--config",
            str(CONFIG),
        )
        decision_path = ARTIFACT_DIR / "registry_decision.json"
        return json.loads(decision_path.read_text(encoding="utf-8"))

    generated = generate_data()
    validated = validate_data()
    trained = train_model()
    registered = register_model()
    smoke = registry_smoke()

    generated >> validated >> trained >> registered >> smoke


training_pipeline()
