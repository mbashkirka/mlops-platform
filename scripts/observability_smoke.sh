#!/bin/sh
set -eu

AIRFLOW_COMPOSE="docker compose -f compose.airflow.yaml"
OBS_COMPOSE="docker compose -f compose.airflow.yaml -f compose.observability.yaml"
API_PORT="${AIRFLOW_API_HOST_PORT:-8001}"
PROM_PORT="${PROMETHEUS_HOST_PORT:-9091}"
GRAFANA_PORT="${GRAFANA_HOST_PORT:-3001}"

echo "[observability-smoke] running Airflow M6 smoke to produce champion and API"
sh scripts/airflow_smoke.sh

echo "[observability-smoke] starting Prometheus and Grafana"
$OBS_COMPOSE up --build -d prometheus grafana

echo "[observability-smoke] generating inference traffic"
python -m mlops_platform.container_smoke \
  --base-url "http://127.0.0.1:${API_PORT}" \
  --wait-seconds 60 >/dev/null

echo "[observability-smoke] validating metrics, scrape target, datasource, and dashboard"
python - "$API_PORT" "$PROM_PORT" "$GRAFANA_PORT" <<'PY'
import base64
import json
import sys
import time
import urllib.parse
import urllib.request

api_port, prom_port, grafana_port = sys.argv[1:]

def get(url, auth=None):
    request = urllib.request.Request(url)
    if auth:
        token = base64.b64encode(auth.encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read().decode()

def wait(url, predicate=lambda body: True, auth=None, timeout=90):
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            body = get(url, auth=auth)
            if predicate(body):
                return body
        except Exception as exc:
            last_error = exc
        time.sleep(2)
    raise SystemExit(f"Timed out waiting for {url}: {last_error}")

metrics = wait(
    f"http://127.0.0.1:{api_port}/metrics",
    lambda body: "mlops_http_requests_total" in body and "mlops_model_ready 1.0" in body,
)
if "mlops_predictions_total" not in metrics:
    raise SystemExit("Prediction metric missing from /metrics")

query = urllib.parse.quote('up{job="mlops-api"}')
prom = wait(
    f"http://127.0.0.1:{prom_port}/api/v1/query?query={query}",
    lambda body: any(
        item.get("value", [None, "0"])[1] == "1"
        for item in json.loads(body).get("data", {}).get("result", [])
    ),
)
if json.loads(prom).get("status") != "success":
    raise SystemExit("Prometheus query failed")

wait(f"http://127.0.0.1:{grafana_port}/api/health")
source = json.loads(
    wait(
        f"http://127.0.0.1:{grafana_port}/api/datasources/uid/prometheus",
        auth="admin:admin",
    )
)
if source.get("url") != "http://prometheus:9090":
    raise SystemExit("Grafana Prometheus datasource is not provisioned correctly")

dashboard = json.loads(
    wait(
        f"http://127.0.0.1:{grafana_port}/api/dashboards/uid/mlops-platform-observability",
        auth="admin:admin",
    )
)
if dashboard.get("dashboard", {}).get("title") != "MLOps Platform Observability":
    raise SystemExit("Grafana dashboard was not provisioned")

print("Prometheus + Grafana M7 smoke: PASSED")
print(f"prometheus=http://127.0.0.1:{prom_port}")
print(f"grafana=http://127.0.0.1:{grafana_port}")
print("dashboard_uid=mlops-platform-observability")
PY

echo "[observability-smoke] stack status"
$OBS_COMPOSE ps -a
