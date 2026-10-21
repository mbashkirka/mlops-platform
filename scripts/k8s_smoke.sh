#!/bin/sh
set -eu

CLUSTER_NAME="${KIND_CLUSTER_NAME:-mlops-platform}"
NAMESPACE="${K8S_NAMESPACE:-mlops-platform}"
APP_IMAGE="${K8S_APP_IMAGE:-mlops-platform:1.0.0}"
KIND_NODE_IMAGE="${KIND_NODE_IMAGE:-kindest/node:v1.36.1@sha256:3489c7674813ba5d8b1a9977baea8a6e553784dab7b84759d1014dbd78f7ebd5}"
CONTEXT="kind-${CLUSTER_NAME}"
API_URL="${K8S_API_URL:-http://127.0.0.1:8002}"
PROM_URL="${K8S_PROMETHEUS_URL:-http://127.0.0.1:9093}"
GRAFANA_URL="${K8S_GRAFANA_URL:-http://127.0.0.1:3002}"

for tool in docker kind kubectl curl python; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "[k8s-smoke] missing required command: $tool" >&2
        exit 2
    fi
done

if kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
    echo "[k8s-smoke] deleting existing kind cluster: $CLUSTER_NAME"
    kind delete cluster --name "$CLUSTER_NAME"
fi

echo "[k8s-smoke] creating kind cluster"
kind create cluster \
    --name "$CLUSTER_NAME" \
    --image "$KIND_NODE_IMAGE" \
    --config k8s/kind-config.yaml \
    --wait 180s

echo "[k8s-smoke] building and loading application image"
docker build --tag "$APP_IMAGE" .
kind load docker-image "$APP_IMAGE" --name "$CLUSTER_NAME"

echo "[k8s-smoke] applying platform foundations"
kubectl --context "$CONTEXT" apply -f k8s/base/namespace.yaml
kubectl --context "$CONTEXT" apply -f k8s/base/configmap.yaml
kubectl --context "$CONTEXT" -n "$NAMESPACE" create secret generic grafana-admin \
    --from-literal=username=admin \
    --from-literal=password=admin \
    --dry-run=client -o yaml | kubectl --context "$CONTEXT" apply -f -
kubectl --context "$CONTEXT" apply -f k8s/base/mlflow.yaml
kubectl --context "$CONTEXT" apply -f k8s/base/kafka.yaml
kubectl --context "$CONTEXT" apply -f k8s/base/prometheus.yaml
kubectl --context "$CONTEXT" apply -f k8s/base/grafana.yaml

kubectl --context "$CONTEXT" -n "$NAMESPACE" rollout status deployment/mlflow --timeout=300s
kubectl --context "$CONTEXT" -n "$NAMESPACE" rollout status statefulset/kafka --timeout=300s

echo "[k8s-smoke] bootstrapping champion model and Kafka topic"
kubectl --context "$CONTEXT" delete job model-bootstrap kafka-topic-init \
    -n "$NAMESPACE" --ignore-not-found
kubectl --context "$CONTEXT" apply -f k8s/base/bootstrap-job.yaml
if ! kubectl --context "$CONTEXT" -n "$NAMESPACE" wait \
    --for=condition=complete job/model-bootstrap --timeout=360s; then
    echo "[k8s-smoke] model-bootstrap failed or timed out" >&2
    kubectl --context "$CONTEXT" -n "$NAMESPACE" get pods -o wide >&2 || true
    kubectl --context "$CONTEXT" -n "$NAMESPACE" logs \
        job/model-bootstrap --all-containers=true --prefix=true --tail=200 >&2 || true
    exit 1
fi

echo "[k8s-smoke] verifying MLflow stayed healthy during bootstrap"
kubectl --context "$CONTEXT" -n "$NAMESPACE" wait \
    --for=condition=Available deployment/mlflow --timeout=180s
mlflow_restarts="$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get pod \
    -l app=mlflow -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}')"
if [ "${mlflow_restarts:-0}" -ne 0 ]; then
    echo "[k8s-smoke] MLflow restarted during model bootstrap: $mlflow_restarts" >&2
    kubectl --context "$CONTEXT" -n "$NAMESPACE" describe pod -l app=mlflow >&2 || true
    exit 1
fi
echo "mlflow_restarts=$mlflow_restarts"

kubectl --context "$CONTEXT" apply -f k8s/base/kafka-init-job.yaml
kubectl --context "$CONTEXT" -n "$NAMESPACE" wait \
    --for=condition=complete job/kafka-topic-init --timeout=180s

echo "[k8s-smoke] starting API and durable Kafka consumer"
kubectl --context "$CONTEXT" apply -f k8s/base/api.yaml
kubectl --context "$CONTEXT" apply -f k8s/base/kafka-consumer.yaml
kubectl --context "$CONTEXT" -n "$NAMESPACE" rollout status deployment/api --timeout=300s
kubectl --context "$CONTEXT" -n "$NAMESPACE" rollout status deployment/kafka-consumer --timeout=180s
kubectl --context "$CONTEXT" -n "$NAMESPACE" rollout status deployment/prometheus --timeout=180s
kubectl --context "$CONTEXT" -n "$NAMESPACE" rollout status deployment/grafana --timeout=180s

python -m mlops_platform.container_smoke \
    --config configs/train.yaml \
    --base-url "$API_URL" \
    --wait-seconds 180

echo "[k8s-smoke] generating Kafka-backed inference traffic"
python - "$API_URL" <<'PYEVENTS'
import json
import sys
import urllib.request

base_url = sys.argv[1].rstrip("/")
with urllib.request.urlopen(f"{base_url}/v1/model-info", timeout=5) as response:
    info = json.load(response)
features = {f"feature_{index:02d}": 0.0 for index in range(int(info["n_features"]))}
payload = json.dumps({"features": features}).encode()
for _ in range(50):
    request = urllib.request.Request(
        f"{base_url}/v1/predict",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 200
print("produced_events=50")
PYEVENTS

consumer_pod="$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get pod \
    -l app=kafka-consumer -o jsonpath='{.items[0].metadata.name}')"

echo "[k8s-smoke] waiting for durable event persistence"
deadline=$(( $(date +%s) + 120 ))
while :; do
    persisted="$(kubectl --context "$CONTEXT" -n "$NAMESPACE" exec "$consumer_pod" -- \
        sh -c 'test -f /var/lib/mlops/events/prediction_events.jsonl && wc -l < /var/lib/mlops/events/prediction_events.jsonl || echo 0' \
        | tr -d '[:space:]')"
    if [ "${persisted:-0}" -ge 51 ]; then
        break
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "[k8s-smoke] consumer did not persist expected events" >&2
        exit 1
    fi
    sleep 2
done

echo "persisted_events=$persisted"

kafka_pod="$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get pod \
    -l app=kafka -o jsonpath='{.items[0].metadata.name}')"
kubectl --context "$CONTEXT" -n "$NAMESPACE" exec "$kafka_pod" -- \
    /opt/kafka/bin/kafka-consumer-groups.sh \
    --bootstrap-server kafka:19092 \
    --describe \
    --group mlops-monitoring-v1

echo "[k8s-smoke] validating Prometheus and Grafana endpoints"
curl -fsS "$PROM_URL/-/ready" >/dev/null
curl -fsS "$GRAFANA_URL/api/health" >/dev/null
python - "$PROM_URL" <<'PYPROM'
import json
import sys
import urllib.parse
import urllib.request

url = sys.argv[1].rstrip("/")
query = urllib.parse.quote('up{job="mlops-api"}')
with urllib.request.urlopen(f"{url}/api/v1/query?query={query}", timeout=5) as response:
    payload = json.load(response)
assert payload["status"] == "success", payload
values = payload["data"]["result"]
assert values and any(float(item["value"][1]) == 1.0 for item in values), payload
print("prometheus_api_up=1")
PYPROM

echo "[k8s-smoke] exercising zero-unavailable rolling update"
marker="$(date +%s)"
kubectl --context "$CONTEXT" -n "$NAMESPACE" set env deployment/api \
    M10_ROLLOUT_MARKER="$marker" >/dev/null
kubectl --context "$CONTEXT" -n "$NAMESPACE" rollout status deployment/api --timeout=300s
curl -fsS "$API_URL/ready" >/dev/null

echo "M10 Kubernetes deployment smoke: PASSED"
echo "cluster=$CLUSTER_NAME"
echo "kubernetes_node_image=$KIND_NODE_IMAGE"
echo "api=$API_URL"
echo "mlflow=http://127.0.0.1:5052"
echo "prometheus=$PROM_URL"
echo "grafana=$GRAFANA_URL"
echo "persisted_events=$persisted"
