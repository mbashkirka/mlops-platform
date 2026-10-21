from __future__ import annotations

import json
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
K8S = ROOT / "k8s" / "base"


def _version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _documents(name: str) -> list[dict]:
    return [item for item in yaml.safe_load_all((K8S / name).read_text(encoding="utf-8")) if item]


def _kind(documents: list[dict], kind: str, name: str) -> dict:
    return next(
        item for item in documents if item["kind"] == kind and item["metadata"]["name"] == name
    )


def test_kind_cluster_pins_supported_node_and_host_ports() -> None:
    config = yaml.safe_load((ROOT / "k8s/kind-config.yaml").read_text(encoding="utf-8"))
    assert config["kind"] == "Cluster"
    mappings = config["nodes"][0]["extraPortMappings"]
    pairs = {(item["containerPort"], item["hostPort"]) for item in mappings}
    assert pairs == {(30080, 8002), (30500, 5052), (30090, 9093), (30300, 3002)}
    script = (ROOT / "scripts/k8s_smoke.sh").read_text(encoding="utf-8")
    assert "kindest/node:v1.36.1@sha256:" in script


def test_embedded_training_config_matches_canonical_config() -> None:
    configmap = yaml.safe_load((K8S / "configmap.yaml").read_text(encoding="utf-8"))
    embedded = yaml.safe_load(configmap["data"]["train.yaml"])
    canonical = yaml.safe_load((ROOT / "configs/train.yaml").read_text(encoding="utf-8"))
    assert embedded == canonical


def test_api_deployment_is_replicated_secure_and_zero_unavailable() -> None:
    documents = _documents("api.yaml")
    deployment = _kind(documents, "Deployment", "api")
    service = _kind(documents, "Service", "api")
    spec = deployment["spec"]
    container = spec["template"]["spec"]["containers"][0]

    assert spec["replicas"] == 2
    assert spec["strategy"]["rollingUpdate"] == {"maxUnavailable": 0, "maxSurge": 1}
    assert container["image"] == f"mlops-platform:{_version()}"
    assert container["securityContext"]["runAsNonRoot"] is True
    assert container["securityContext"]["runAsUser"] == 10001
    assert container["readinessProbe"]["httpGet"]["path"] == "/ready"
    assert container["livenessProbe"]["httpGet"]["path"] == "/health"
    assert container["startupProbe"]["httpGet"]["path"] == "/health"
    assert container["resources"]["requests"]["memory"] == "256Mi"
    assert service["spec"]["ports"][0]["nodePort"] == 30080


def test_kafka_statefulset_keeps_non_root_storage_contract() -> None:
    documents = _documents("kafka.yaml")
    headless = _kind(documents, "Service", "kafka-headless")
    statefulset = _kind(documents, "StatefulSet", "kafka")
    pod_spec = statefulset["spec"]["template"]["spec"]
    init = pod_spec["initContainers"][0]
    kafka = pod_spec["containers"][0]

    assert statefulset["spec"]["replicas"] == 1
    assert statefulset["spec"]["serviceName"] == "kafka-headless"
    assert headless["spec"]["clusterIP"] == "None"
    assert headless["spec"]["publishNotReadyAddresses"] is True
    assert init["image"] == "alpine:3.22"
    assert init["securityContext"]["runAsUser"] == 0
    assert "chown -R 1000:1000 /var/lib/kafka/data" in init["command"][-1]
    assert kafka["image"] == "apache/kafka:4.3.1"
    assert kafka["securityContext"]["runAsNonRoot"] is True
    assert kafka["securityContext"]["runAsUser"] == 1000
    pvc = statefulset["spec"]["volumeClaimTemplates"][0]
    assert pvc["spec"]["resources"]["requests"]["storage"] == "2Gi"


def test_mlflow_bootstrap_and_topic_jobs_use_cluster_services() -> None:
    mlflow = _kind(_documents("mlflow.yaml"), "Deployment", "mlflow")
    container = mlflow["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == f"mlops-platform:{_version()}"
    command = container["command"]
    workers_index = command.index("--workers")
    assert command[workers_index + 1] == "1"
    assert container["resources"]["requests"]["memory"] == "512Mi"
    assert container["resources"]["limits"]["memory"] == "2Gi"
    assert container["startupProbe"]["timeoutSeconds"] == 3

    bootstrap = yaml.safe_load((K8S / "bootstrap-job.yaml").read_text(encoding="utf-8"))
    bootstrap_env = bootstrap["spec"]["template"]["spec"]["containers"][0]["env"]
    bootstrap_values = {item["name"]: item["value"] for item in bootstrap_env}
    assert bootstrap_values["MLFLOW_TRACKING_URI"] == "http://mlflow:5000"

    topic = yaml.safe_load((K8S / "kafka-init-job.yaml").read_text(encoding="utf-8"))
    topic_env = topic["spec"]["template"]["spec"]["containers"][0]["env"]
    topic_values = {item["name"]: item["value"] for item in topic_env}
    assert topic_values["MLOPS_KAFKA_BOOTSTRAP_SERVERS"] == "kafka:19092"


def test_observability_is_provisioned_without_hardcoded_secret() -> None:
    prometheus_docs = _documents("prometheus.yaml")
    prometheus = _kind(prometheus_docs, "Deployment", "prometheus")
    prom_container = prometheus["spec"]["template"]["spec"]["containers"][0]
    assert prom_container["image"] == "prom/prometheus:v3.14.0"

    grafana_docs = _documents("grafana.yaml")
    grafana = _kind(grafana_docs, "Deployment", "grafana")
    container = grafana["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "grafana/grafana:13.2.0"
    env = {item["name"]: item for item in container["env"]}
    password = env["GF_SECURITY_ADMIN_PASSWORD"]
    assert password["valueFrom"]["secretKeyRef"]["name"] == "grafana-admin"
    assert "value" not in password

    dashboard_cm = _kind(grafana_docs, "ConfigMap", "grafana-dashboard")
    dashboard = json.loads(dashboard_cm["data"]["mlops-platform.json"])
    assert dashboard["uid"] == "mlops-platform-observability"


def test_consumer_persists_events_on_pvc() -> None:
    documents = _documents("kafka-consumer.yaml")
    deployment = _kind(documents, "Deployment", "kafka-consumer")
    pvc = _kind(documents, "PersistentVolumeClaim", "kafka-events")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    command = " ".join(container["command"])
    assert "/var/lib/mlops/events/prediction_events.jsonl" in command
    assert "/var/lib/mlops/monitoring/current_batch.csv" in command
    assert pvc["spec"]["resources"]["requests"]["storage"] == "2Gi"


def test_kubernetes_smoke_exercises_real_rollout_and_event_path() -> None:
    script = (ROOT / "scripts/k8s_smoke.sh").read_text(encoding="utf-8")
    assert "kind create cluster" in script
    assert "kind load docker-image" in script
    assert "job/model-bootstrap" in script
    assert "condition=Available deployment/mlflow" in script
    assert "mlflow_restarts=" in script
    assert "job/kafka-topic-init" in script
    assert "produced_events=50" in script
    assert "kafka-consumer-groups.sh" in script
    assert "set env deployment/api" in script
    assert "rollout status deployment/api" in script
