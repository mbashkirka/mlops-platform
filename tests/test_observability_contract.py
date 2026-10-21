import json
import tomllib
from pathlib import Path

import yaml


def _version() -> str:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    return str(project["project"]["version"])


def test_observability_overlay_pins_prometheus_and_grafana() -> None:
    compose = yaml.safe_load(Path("compose.observability.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert services["prometheus"]["image"] == "prom/prometheus:v3.14.0"
    assert services["grafana"]["image"] == "grafana/grafana:13.2.0"
    assert "${PROMETHEUS_HOST_PORT:-9091}:9090" in services["prometheus"]["ports"]
    assert "${GRAFANA_HOST_PORT:-3001}:3000" in services["grafana"]["ports"]


def test_prometheus_scrapes_api_metrics() -> None:
    config = yaml.safe_load(
        Path("observability/prometheus/prometheus.yml").read_text(encoding="utf-8")
    )
    jobs = {item["job_name"]: item for item in config["scrape_configs"]}
    api_job = jobs["mlops-api"]

    assert api_job["metrics_path"] == "/metrics"
    assert api_job["static_configs"][0]["targets"] == ["api:8000"]


def test_grafana_provisions_prometheus_and_dashboard() -> None:
    datasource = yaml.safe_load(
        Path("observability/grafana/provisioning/datasources/prometheus.yml").read_text(
            encoding="utf-8"
        )
    )
    dashboard = json.loads(
        Path("observability/grafana/dashboards/mlops-platform.json").read_text(encoding="utf-8")
    )

    assert datasource["datasources"][0]["url"] == "http://prometheus:9090"
    assert datasource["datasources"][0]["uid"] == "prometheus"
    assert dashboard["uid"] == "mlops-platform-observability"
    assert len(dashboard["panels"]) >= 7


def test_m7_version_is_synchronized() -> None:
    version = _version()
    assert f"PROJECT_VERSION := {version}" in Path("Makefile").read_text(encoding="utf-8")
    assert f"mlops-platform:{version}" in Path("compose.airflow.yaml").read_text(encoding="utf-8")
