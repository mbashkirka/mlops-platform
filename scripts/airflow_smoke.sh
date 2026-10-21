#!/bin/sh
set -eu

COMPOSE="docker compose -f compose.airflow.yaml"
DAG_ID="mlops_training_pipeline"
RUN_ID="m6_smoke_$(date +%Y%m%dT%H%M%S)"
AIRFLOW_HOST_PORT="${AIRFLOW_HOST_PORT:-8080}"
API_HOST_PORT="${AIRFLOW_API_HOST_PORT:-8001}"
WAIT_SECONDS="${AIRFLOW_WAIT_SECONDS:-300}"

echo "[airflow-smoke] validating compose configuration"
$COMPOSE config --quiet

echo "[airflow-smoke] starting Airflow control plane and MLflow"
$COMPOSE up --build -d airflow-apiserver airflow-scheduler airflow-dag-processor mlflow

echo "[airflow-smoke] waiting for API server health"
python - "$AIRFLOW_HOST_PORT" "$WAIT_SECONDS" <<'PY'
import sys
import time
import urllib.request

port = int(sys.argv[1])
deadline = time.monotonic() + int(sys.argv[2])
url = f"http://127.0.0.1:{port}/api/v2/monitor/health"
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            if response.status == 200:
                break
    except Exception:
        time.sleep(2)
else:
    raise SystemExit(f"Airflow API server did not become healthy: {url}")
PY

echo "[airflow-smoke] waiting for DAG discovery"
remaining="$WAIT_SECONDS"
while [ "$remaining" -gt 0 ]; do
  if $COMPOSE exec -T airflow-scheduler airflow dags list -o plain 2>/dev/null \
    | grep -q "$DAG_ID"; then
    break
  fi
  sleep 2
  remaining=$((remaining - 2))
done
if [ "$remaining" -le 0 ]; then
  echo "DAG was not discovered: $DAG_ID" >&2
  $COMPOSE logs --tail=200 airflow-dag-processor airflow-scheduler >&2
  exit 1
fi

$COMPOSE exec -T airflow-scheduler airflow dags unpause "$DAG_ID" >/dev/null

echo "[airflow-smoke] triggering $DAG_ID as $RUN_ID"
$COMPOSE exec -T airflow-scheduler airflow dags trigger -r "$RUN_ID" "$DAG_ID" >/dev/null

echo "[airflow-smoke] waiting for DAG run"
remaining="$WAIT_SECONDS"
state="queued"
while [ "$remaining" -gt 0 ]; do
  state="$($COMPOSE exec -T airflow-scheduler \
    airflow dags state "$DAG_ID" "$RUN_ID" 2>/dev/null \
    | tail -n 1 | tr -d '\r\n ')"
  if [ "$state" = "success" ]; then
    break
  fi
  if [ "$state" = "failed" ]; then
    echo "Airflow DAG failed: $RUN_ID" >&2
    $COMPOSE logs --tail=300 airflow-scheduler >&2
    exit 1
  fi
  sleep 3
  remaining=$((remaining - 3))
done
if [ "$state" != "success" ]; then
  echo "Airflow DAG did not finish successfully; state=$state" >&2
  $COMPOSE logs --tail=300 airflow-scheduler >&2
  exit 1
fi

echo "[airflow-smoke] starting API against the Airflow-produced champion"
$COMPOSE up -d api
python -m mlops_platform.container_smoke \
  --base-url "http://127.0.0.1:${API_HOST_PORT}" \
  --wait-seconds 120

echo "Airflow M6 orchestration smoke: PASSED"
echo "dag_id=$DAG_ID"
echo "run_id=$RUN_ID"
echo "dag_state=$state"
