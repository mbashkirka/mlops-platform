#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "[portfolio-demo] running full Kubernetes platform demonstration"
make k8s-smoke

echo "[portfolio-demo] verifying public demo endpoints"
curl -fsS http://127.0.0.1:8002/health >/dev/null
curl -fsS http://127.0.0.1:8002/ready >/dev/null
curl -fsS http://127.0.0.1:8002/v1/model-info >/dev/null
curl -fsS http://127.0.0.1:9093/-/ready >/dev/null
curl -fsS http://127.0.0.1:3002/api/health >/dev/null

echo "M12 portfolio demo: READY"
echo "api=http://127.0.0.1:8002/docs"
echo "mlflow=http://127.0.0.1:5052"
echo "prometheus=http://127.0.0.1:9093"
echo "grafana=http://127.0.0.1:3002"
echo "cleanup=make k8s-delete"
