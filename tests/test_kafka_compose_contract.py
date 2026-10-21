import tomllib
from pathlib import Path

import yaml


def _version() -> str:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    return str(project["project"]["version"])


def test_kafka_storage_volume_is_prepared_for_non_root_broker() -> None:
    compose = yaml.safe_load(Path("compose.kafka.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    storage_init = services["kafka-storage-init"]
    kafka = services["kafka"]

    assert storage_init["image"] == "alpine:3.22"
    assert storage_init["user"] == "0:0"
    assert "chown -R 1000:1000 /tmp/kraft-combined-logs" in " ".join(storage_init["command"])
    assert "kafka-data:/tmp/kraft-combined-logs" in storage_init["volumes"]
    assert "kafka-data:/tmp/kraft-combined-logs" in kafka["volumes"]
    assert (
        kafka["depends_on"]["kafka-storage-init"]["condition"] == "service_completed_successfully"
    )


def test_kafka_overlay_uses_official_kraft_image_and_explicit_topic_init() -> None:
    compose = yaml.safe_load(Path("compose.kafka.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert services["kafka"]["image"] == "apache/kafka:4.3.1"
    assert services["kafka"]["environment"]["KAFKA_PROCESS_ROLES"] == "broker,controller"
    assert services["kafka"]["environment"]["KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR"] == 1
    assert services["kafka-init"]["depends_on"]["kafka"]["condition"] == "service_healthy"
    assert "mlops_platform.kafka_admin" in services["kafka-init"]["command"]


def test_api_and_consumer_use_internal_kafka_listener() -> None:
    compose = yaml.safe_load(Path("compose.kafka.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    api_env = services["api"]["environment"]
    consumer_env = services["kafka-consumer"]["environment"]
    assert api_env["MLOPS_KAFKA_BOOTSTRAP_SERVERS"] == "kafka:19092"
    assert api_env["MLOPS_KAFKA_PREDICTION_TOPIC"] == "mlops.predictions.v1"
    assert consumer_env["MLOPS_KAFKA_CONSUMER_GROUP"] == "mlops-monitoring-v1"
    assert "./data/monitoring:/app/data/monitoring" in services["kafka-consumer"]["volumes"]


def test_airflow_and_consumer_share_the_host_monitoring_batch_directory() -> None:
    airflow = yaml.safe_load(Path("compose.airflow.yaml").read_text(encoding="utf-8"))
    kafka = yaml.safe_load(Path("compose.kafka.yaml").read_text(encoding="utf-8"))

    airflow_volumes = airflow["x-airflow-common"]["volumes"]
    consumer_volumes = kafka["services"]["kafka-consumer"]["volumes"]
    assert "./data/monitoring:/opt/airflow/project/data/monitoring" in airflow_volumes
    assert "./data/monitoring:/app/data/monitoring" in consumer_volumes


def test_kafka_images_follow_current_project_version() -> None:
    version = _version()
    compose = Path("compose.kafka.yaml").read_text(encoding="utf-8")
    assert f"image: mlops-platform:{version}" in compose


def test_kafka_python_client_is_scoped_to_serving_and_dev_extras() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    extras = project["optional-dependencies"]
    assert any(item.startswith("confluent-kafka>=2.15") for item in extras["serve"])
    assert any(item.startswith("confluent-kafka>=2.15") for item in extras["dev"])
    assert not any(item.startswith("confluent-kafka") for item in project["dependencies"])


def test_grafana_dashboard_contains_kafka_publish_panel() -> None:
    import json

    dashboard = json.loads(
        Path("observability/grafana/dashboards/mlops-platform.json").read_text(encoding="utf-8")
    )
    expressions = [
        target["expr"] for panel in dashboard["panels"] for target in panel.get("targets", [])
    ]
    assert any("mlops_kafka_publish_total" in expression for expression in expressions)
