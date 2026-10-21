import tomllib
from pathlib import Path

import yaml


def _project_version() -> str:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    return str(pyproject["project"]["version"])


def test_dockerfile_runs_as_non_root_with_readiness_healthcheck() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "USER app" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "/ready" in dockerfile
    assert '"--host", "0.0.0.0"' in dockerfile


def test_compose_bootstrap_gates_api_startup() -> None:
    compose = yaml.safe_load(Path("compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert set(services) == {"mlflow", "bootstrap", "api"}
    assert services["bootstrap"]["depends_on"]["mlflow"]["condition"] == "service_healthy"
    bootstrap_condition = services["api"]["depends_on"]["bootstrap"]["condition"]
    assert bootstrap_condition == "service_completed_successfully"
    assert services["api"]["environment"]["MLFLOW_TRACKING_URI"] == "http://mlflow:5000"


def test_compose_uses_configurable_host_ports_and_current_image() -> None:
    compose_text = Path("compose.yaml").read_text(encoding="utf-8")
    version = _project_version()

    assert f"image: mlops-platform:{version}" in compose_text
    assert "${MLFLOW_HOST_PORT:-5050}:5000" in compose_text
    assert "${API_HOST_PORT:-8000}:8000" in compose_text


def test_makefile_container_smoke_uses_configurable_api_port() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    version = _project_version()

    assert f"PROJECT_VERSION := {version}" in makefile
    assert "MLFLOW_HOST_PORT ?= 5050" in makefile
    assert "API_HOST_PORT ?= 8000" in makefile
    assert "127.0.0.1:$(API_HOST_PORT)" in makefile
