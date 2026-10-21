from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from airflow.providers.standard.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.sdk import dag, task

PROJECT_ROOT = Path(os.getenv("MLOPS_AIRFLOW_PROJECT_ROOT", "/opt/airflow/project"))
CONFIG = Path(os.getenv("MLOPS_CONFIG", PROJECT_ROOT / "configs/train.yaml"))
BATCH = PROJECT_ROOT / "data/monitoring/current_batch.csv"
ARTIFACT_DIR = PROJECT_ROOT / "artifacts"


def _run(*args: str) -> None:
    subprocess.run(args, cwd=PROJECT_ROOT, check=True)


@dag(
    dag_id="mlops_monitoring_pipeline",
    schedule=None,
    catchup=False,
    max_active_runs=1,
    tags=["mlops-platform", "monitoring", "drift", "retraining"],
)
def monitoring_pipeline():
    @task
    def evaluate_production_batch() -> dict[str, object]:
        _run(
            "python",
            "-m",
            "mlops_platform.monitoring",
            "--config",
            str(CONFIG),
            "--batch",
            str(BATCH),
        )
        decision_path = ARTIFACT_DIR / "retraining_decision.json"
        return json.loads(decision_path.read_text(encoding="utf-8"))

    @task.branch
    def route_retraining(decision: dict[str, object]) -> str:
        if bool(decision["retrain_required"]):
            return "trigger_retraining"
        return "no_retraining"

    @task
    def no_retraining(decision: dict[str, object]) -> None:
        print(json.dumps(decision, sort_keys=True))

    decision = evaluate_production_batch()
    route = route_retraining(decision)
    no_action = no_retraining(decision)
    retrain = TriggerDagRunOperator(
        task_id="trigger_retraining",
        trigger_dag_id="mlops_training_pipeline",
        conf={"trigger_source": "mlops_monitoring_pipeline"},
        wait_for_completion=True,
        poke_interval=3,
        allowed_states=["success"],
        failed_states=["failed"],
    )

    decision >> route
    route >> [no_action, retrain]


monitoring_pipeline()
