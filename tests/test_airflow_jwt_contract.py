from pathlib import Path

import yaml


def test_airflow_execution_jwt_secret_is_shared_and_overrideable() -> None:
    compose = yaml.safe_load(Path("compose.airflow.yaml").read_text(encoding="utf-8"))
    airflow_env = compose["x-airflow-environment"]

    jwt_secret = airflow_env["AIRFLOW__API_AUTH__JWT_SECRET"]
    api_secret = airflow_env["AIRFLOW__API__SECRET_KEY"]

    assert jwt_secret.startswith("${AIRFLOW_JWT_SECRET:-")
    assert api_secret.startswith("${AIRFLOW_API_SECRET_KEY:-")
    assert len(jwt_secret.removeprefix("${AIRFLOW_JWT_SECRET:-").removesuffix("}")) >= 64
    assert len(api_secret.removeprefix("${AIRFLOW_API_SECRET_KEY:-").removesuffix("}")) >= 64


def test_all_airflow_services_inherit_shared_environment() -> None:
    compose = yaml.safe_load(Path("compose.airflow.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    for service_name in (
        "airflow-init",
        "airflow-apiserver",
        "airflow-scheduler",
        "airflow-dag-processor",
    ):
        environment = services[service_name]["environment"]
        assert "AIRFLOW__API_AUTH__JWT_SECRET" in environment
        assert "AIRFLOW__API__SECRET_KEY" in environment
