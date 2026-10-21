import tomllib
from pathlib import Path

import yaml


def test_airflow_dockerfile_pins_current_airflow_and_project_dependencies() -> None:
    dockerfile = Path("Dockerfile.airflow").read_text(encoding="utf-8")

    assert "apache/airflow:${AIRFLOW_VERSION}-python3.12" in dockerfile
    assert '"apache-airflow==${AIRFLOW_VERSION}"' in dockerfile
    assert "pip install --no-cache-dir --no-deps ." in dockerfile
    assert "pip check" in dockerfile


def test_airflow_compose_has_required_airflow3_control_plane() -> None:
    compose = yaml.safe_load(Path("compose.airflow.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    required = {
        "airflow-db",
        "mlflow",
        "airflow-init",
        "airflow-apiserver",
        "airflow-scheduler",
        "airflow-dag-processor",
        "api",
    }
    assert set(services) == required
    assert services["airflow-db"]["image"] == "postgres:16-alpine"
    assert services["airflow-scheduler"]["command"] == "scheduler"
    assert services["airflow-dag-processor"]["command"] == "dag-processor"
    assert services["airflow-apiserver"]["command"] == "api-server"


def test_airflow_compose_uses_local_executor_and_mlflow_network_uri() -> None:
    compose_text = Path("compose.airflow.yaml").read_text(encoding="utf-8")

    assert "AIRFLOW__CORE__EXECUTOR: LocalExecutor" in compose_text
    assert "AIRFLOW__CORE__EXECUTION_API_SERVER_URL" in compose_text
    assert "MLFLOW_TRACKING_URI: http://mlflow:5000" in compose_text
    assert "${AIRFLOW_HOST_PORT:-8080}:8080" in compose_text
    assert "${AIRFLOW_MLFLOW_HOST_PORT:-5051}:5000" in compose_text
    assert "${AIRFLOW_API_HOST_PORT:-8001}:8000" in compose_text


def test_dag_uses_airflow_sdk_and_expected_pipeline_order() -> None:
    dag_source = Path("dags/mlops_training_pipeline.py").read_text(encoding="utf-8")

    assert "from airflow.sdk import dag, task" in dag_source
    for task_name in (
        "generate_data",
        "validate_data",
        "train_model",
        "register_model",
        "registry_smoke",
    ):
        assert f"def {task_name}" in dag_source
    assert "generated >> validated >> trained >> registered >> smoke" in dag_source


def test_airflow_smoke_triggers_scheduler_run_and_serving_validation() -> None:
    smoke = Path("scripts/airflow_smoke.sh").read_text(encoding="utf-8")

    assert "airflow dags trigger" in smoke
    assert "airflow dags state" in smoke
    assert "mlops_platform.container_smoke" in smoke
    assert "Airflow M6 orchestration smoke: PASSED" in smoke


def test_serving_dependencies_are_isolated_from_airflow_core() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    core = project["dependencies"]
    optional = project["optional-dependencies"]

    assert not any(item.startswith("fastapi") for item in core)
    assert not any(item.startswith("uvicorn") for item in core)
    assert any(item.startswith("fastapi") for item in optional["serve"])
    assert any(item.startswith("uvicorn") for item in optional["serve"])
    assert any(item.startswith("fastapi") for item in optional["dev"])
    assert any(item.startswith("uvicorn") for item in optional["dev"])


def test_api_dockerfile_installs_serving_extra() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert 'python -m pip install ".[serve]"' in dockerfile


def test_airflow_compose_uses_shared_execution_jwt_secret() -> None:
    compose = yaml.safe_load(Path("compose.airflow.yaml").read_text(encoding="utf-8"))
    airflow_env = compose["x-airflow-environment"]

    jwt_secret = airflow_env["AIRFLOW__API_AUTH__JWT_SECRET"]
    api_secret = airflow_env["AIRFLOW__API__SECRET_KEY"]

    assert "AIRFLOW_JWT_SECRET" in jwt_secret
    assert "AIRFLOW_API_SECRET_KEY" in api_secret
    assert len(jwt_secret) >= 64
    assert len(api_secret) >= 64
