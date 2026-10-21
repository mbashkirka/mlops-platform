"""Minimal local inference smoke test."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib

from mlops_platform.data import feature_columns, load_config, read_dataset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=Path("artifacts/model.joblib"))
    parser.add_argument("--data", type=Path, default=Path("data/raw/dataset.csv"))
    parser.add_argument("--config", type=Path, default=Path("configs/train.yaml"))
    parser.add_argument("--sample-index", type=int, default=0)
    args = parser.parse_args()

    config = load_config(args.config)
    frame = read_dataset(args.data)
    if not 0 <= args.sample_index < len(frame):
        raise ValueError(f"sample-index must be in [0, {len(frame) - 1}]")

    features = feature_columns(int(config["dataset"]["n_features"]))
    model = joblib.load(args.model)
    row = frame.iloc[[args.sample_index]]
    probability = float(model.predict_proba(row[features])[0, 1])

    print(
        json.dumps(
            {
                "sample_index": args.sample_index,
                "row_id": int(row["row_id"].iloc[0]),
                "probability": probability,
                "prediction": int(probability >= 0.5),
                "target": int(row["target"].iloc[0]),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
