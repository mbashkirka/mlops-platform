#!/bin/sh
set -eu

CONFIG="${MLOPS_CONFIG:-configs/train.yaml}"
DATASET="data/raw/dataset.csv"
ARTIFACT_DIR="artifacts"

echo "[bootstrap] generating deterministic dataset"
python -m mlops_platform.data --config "$CONFIG" --output "$DATASET"

echo "[bootstrap] validating dataset contract"
python -m mlops_platform.data_validation \
  --config "$CONFIG" \
  --input "$DATASET" \
  --report "$ARTIFACT_DIR/data_validation.json" \
  --manifest "$ARTIFACT_DIR/data_manifest.json"

echo "[bootstrap] training and logging model to MLflow"
python -m mlops_platform.train --config "$CONFIG" --data "$DATASET"

echo "[bootstrap] registering candidate and promoting qualified champion"
python -m mlops_platform.registry --config "$CONFIG"

echo "[bootstrap] validating Registry aliases"
python -m mlops_platform.registry_smoke --config "$CONFIG"

echo "[bootstrap] complete"
