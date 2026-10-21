#!/bin/sh
set -eu

COMPOSE="docker compose -f compose.airflow.yaml -f compose.observability.yaml"
AIRFLOW_COMPOSE="docker compose -f compose.airflow.yaml"
DAG_ID="mlops_monitoring_pipeline"
WAIT_SECONDS="${AIRFLOW_WAIT_SECONDS:-300}"
API_PORT="${AIRFLOW_API_HOST_PORT:-8001}"

wait_for_run() {
  run_id="$1"
  remaining="$WAIT_SECONDS"
  state="queued"
  while [ "$remaining" -gt 0 ]; do
    state="$($AIRFLOW_COMPOSE exec -T airflow-scheduler \
      airflow dags state "$DAG_ID" "$run_id" 2>/dev/null \
      | tail -n 1 | tr -d '\r\n ')"
    if [ "$state" = "success" ]; then
      return 0
    fi
    if [ "$state" = "failed" ]; then
      echo "Monitoring DAG failed: $run_id" >&2
      $AIRFLOW_COMPOSE logs --tail=300 airflow-scheduler >&2
      return 1
    fi
    sleep 3
    remaining=$((remaining - 3))
  done
  echo "Monitoring DAG did not finish; state=$state" >&2
  return 1
}

read_decision() {
  $AIRFLOW_COMPOSE exec -T airflow-scheduler \
    cat /opt/airflow/project/artifacts/retraining_decision.json
}

echo "[monitoring-smoke] running M7 observability smoke"
sh scripts/observability_smoke.sh

remaining="$WAIT_SECONDS"
while [ "$remaining" -gt 0 ]; do
  if $AIRFLOW_COMPOSE exec -T airflow-scheduler airflow dags list -o plain 2>/dev/null \
    | grep -q "$DAG_ID"; then
    break
  fi
  sleep 2
  remaining=$((remaining - 2))
done
if [ "$remaining" -le 0 ]; then
  echo "Monitoring DAG was not discovered: $DAG_ID" >&2
  exit 1
fi
$AIRFLOW_COMPOSE exec -T airflow-scheduler airflow dags unpause "$DAG_ID" >/dev/null

echo "[monitoring-smoke] stable batch must not trigger retraining"
$AIRFLOW_COMPOSE exec -T airflow-scheduler \
  python -m mlops_platform.monitoring_batch \
  --config /opt/airflow/project/configs/train.yaml \
  --source /opt/airflow/project/data/raw/dataset.csv \
  --output /opt/airflow/project/data/monitoring/current_batch.csv \
  --mode stable >/dev/null

stable_run="m8_stable_$(date +%Y%m%dT%H%M%S)"
$AIRFLOW_COMPOSE exec -T airflow-scheduler \
  airflow dags trigger -r "$stable_run" "$DAG_ID" >/dev/null
wait_for_run "$stable_run"
stable_decision="$(read_decision)"
python - "$stable_decision" <<'PYSTABLE'
import json
import sys

decision = json.loads(sys.argv[1])
assert decision["action"] == "no_action", decision
assert decision["retrain_required"] is False, decision
assert decision["data_quality_status"] == "passed", decision
print("stable_decision=no_action")
PYSTABLE

echo "[monitoring-smoke] drifted batch must trigger retraining"
$AIRFLOW_COMPOSE exec -T airflow-scheduler \
  python -m mlops_platform.monitoring_batch \
  --config /opt/airflow/project/configs/train.yaml \
  --source /opt/airflow/project/data/raw/dataset.csv \
  --output /opt/airflow/project/data/monitoring/current_batch.csv \
  --mode drifted \
  --drift-features 8 \
  --shift-sigma 3.0 >/dev/null

drift_run="m8_drift_$(date +%Y%m%dT%H%M%S)"
$AIRFLOW_COMPOSE exec -T airflow-scheduler \
  airflow dags trigger -r "$drift_run" "$DAG_ID" >/dev/null
wait_for_run "$drift_run"
drift_decision="$(read_decision)"
python - "$drift_decision" <<'PYDRIFT'
import json
import sys

decision = json.loads(sys.argv[1])
assert decision["action"] == "retrain", decision
assert decision["retrain_required"] is True, decision
assert decision["drift_status"] == "drifted", decision
assert decision["drifted_feature_ratio"] >= 0.25, decision
print("drift_decision=retrain")
PYDRIFT

echo "[monitoring-smoke] restarting API to load the newly promoted champion"
$COMPOSE restart api >/dev/null
python -m mlops_platform.container_smoke \
  --base-url "http://127.0.0.1:${API_PORT}" \
  --wait-seconds 120 >/dev/null

model_version="$(python - "$API_PORT" <<'PYVERSION'
import json
import sys
import urllib.request

port = sys.argv[1]
url = f"http://127.0.0.1:{port}/v1/model-info"
with urllib.request.urlopen(url, timeout=5) as response:
    print(json.load(response)["version"])
PYVERSION
)"
if [ "$model_version" -lt 2 ]; then
  echo "Expected retraining to promote model version >=2, got $model_version" >&2
  exit 1
fi

echo "M8 drift monitoring + retraining smoke: PASSED"
echo "stable_run_id=$stable_run"
echo "drift_run_id=$drift_run"
echo "champion_model_version=$model_version"
