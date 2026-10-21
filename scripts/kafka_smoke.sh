#!/bin/sh
set -eu

COMPOSE="docker compose -f compose.airflow.yaml -f compose.observability.yaml -f compose.kafka.yaml"
API_PORT="${AIRFLOW_API_HOST_PORT:-8001}"
WAIT_SECONDS="${KAFKA_WAIT_SECONDS:-180}"
EVENT_COUNT="${KAFKA_SMOKE_EVENT_COUNT:-250}"

wait_healthy() {
  service="$1"
  remaining="$WAIT_SECONDS"
  while [ "$remaining" -gt 0 ]; do
    container_id="$($COMPOSE ps -q "$service" 2>/dev/null || true)"
    status=""
    if [ -n "$container_id" ]; then
      status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null || true)"
    fi
    if [ "$status" = "healthy" ] || [ "$status" = "running" ]; then
      return 0
    fi
    sleep 3
    remaining=$((remaining - 3))
  done
  echo "Service did not become healthy: $service" >&2
  $COMPOSE ps -a >&2
  return 1
}

echo "[kafka-smoke] running M8 monitoring smoke first"
sh scripts/monitoring_smoke.sh

echo "[kafka-smoke] starting Kafka, topic initializer, and durable consumer"
$COMPOSE up --build -d kafka kafka-init kafka-consumer
wait_healthy kafka
wait_healthy kafka-consumer

echo "[kafka-smoke] recreating API with Kafka publishing enabled"
$COMPOSE up --build -d --force-recreate api
python -m mlops_platform.container_smoke   --base-url "http://127.0.0.1:${API_PORT}"   --wait-seconds 120 >/dev/null

echo "[kafka-smoke] generating ${EVENT_COUNT} prediction events"
python - "$API_PORT" "$EVENT_COUNT" <<'PYTRAFFIC'
import json
import sys
import urllib.request

port = sys.argv[1]
count = int(sys.argv[2])
url = f"http://127.0.0.1:{port}/v1/predict"
features = {f"feature_{index:02d}": 0.0 for index in range(20)}
request_ids = []
for _ in range(count):
    request = urllib.request.Request(
        url,
        data=json.dumps({"features": features}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.load(response)
    request_ids.append(payload["request_id"])
assert len(request_ids) == count
assert len(set(request_ids)) == count
print(f"produced_events={count}")
PYTRAFFIC

echo "[kafka-smoke] waiting for consumer persistence"
remaining="$WAIT_SECONDS"
lines=0
while [ "$remaining" -gt 0 ]; do
  lines="$($COMPOSE exec -T kafka-consumer sh -c     'test -f /var/lib/mlops/events/prediction_events.jsonl && wc -l < /var/lib/mlops/events/prediction_events.jsonl || echo 0'     | tr -d '[:space:]')"
  if [ "$lines" -ge "$EVENT_COUNT" ]; then
    break
  fi
  sleep 3
  remaining=$((remaining - 3))
done
if [ "$lines" -lt "$EVENT_COUNT" ]; then
  echo "Expected at least ${EVENT_COUNT} persisted Kafka events, got ${lines}" >&2
  $COMPOSE logs --tail=200 kafka kafka-consumer api >&2
  exit 1
fi

$COMPOSE exec -T kafka-consumer python - "$EVENT_COUNT" <<'PYVERIFY'
import json
import sys
from pathlib import Path

import pandas as pd

expected = int(sys.argv[1])
log_path = Path("/var/lib/mlops/events/prediction_events.jsonl")
events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line]
assert len(events) >= expected, len(events)
recent = events[-expected:]
assert len({event["request_id"] for event in recent}) == expected
assert all(event["schema_version"] == "1.0" for event in recent)
assert all(event["event_type"] == "prediction" for event in recent)
assert all(len(event["features"]) == 20 for event in recent)
assert all(event["model_alias"] == "champion" for event in recent)

batch = pd.read_csv("/app/data/monitoring/current_batch.csv")
assert len(batch) >= expected, len(batch)
assert {f"feature_{index:02d}" for index in range(20)}.issubset(batch.columns)
print(f"persisted_events={len(events)}")
print(f"monitoring_batch_rows={len(batch)}")
PYVERIFY

echo "[kafka-smoke] validating Kafka publish metrics"
metrics="$(curl -fsS "http://127.0.0.1:${API_PORT}/metrics")"
echo "$metrics" | grep -q 'mlops_kafka_publish_total{status="queued"}'

echo "[kafka-smoke] validating topic and consumer group"
$COMPOSE exec -T kafka /opt/kafka/bin/kafka-topics.sh   --bootstrap-server kafka:19092   --describe   --topic mlops.predictions.v1
$COMPOSE exec -T kafka /opt/kafka/bin/kafka-consumer-groups.sh   --bootstrap-server kafka:19092   --describe   --group mlops-monitoring-v1

echo "M9 Kafka event-driven inference smoke: PASSED"
echo "kafka_version=4.3.1"
echo "topic=mlops.predictions.v1"
echo "consumer_group=mlops-monitoring-v1"
echo "persisted_events=$lines"
