"""Create deterministic stable or drifted monitoring batches for local demos."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from mlops_platform.data import feature_columns, load_config, read_dataset, write_dataset


def build_monitoring_batch(
    frame: pd.DataFrame,
    *,
    features: list[str],
    mode: str,
    drift_features: int,
    shift_sigma: float,
) -> pd.DataFrame:
    """Materialize a production-like batch while preserving determinism."""
    batch = frame[["row_id", *features]].copy()
    if mode == "stable":
        return batch
    if mode != "drifted":
        raise ValueError(f"unsupported monitoring mode: {mode}")

    count = min(max(int(drift_features), 1), len(features))
    for name in features[:count]:
        values = batch[name].to_numpy(dtype=float)
        scale = float(np.std(values, ddof=0))
        batch[name] = values + float(shift_sigma) * max(scale, 1e-6)
    return batch


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/train.yaml"))
    parser.add_argument("--source", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/monitoring/current_batch.csv"),
    )
    parser.add_argument("--mode", choices=("stable", "drifted"), default="stable")
    parser.add_argument("--drift-features", type=int, default=8)
    parser.add_argument("--shift-sigma", type=float, default=3.0)
    args = parser.parse_args()

    config = load_config(args.config)
    source = args.source or Path(config["paths"]["dataset"])
    features = feature_columns(int(config["dataset"]["n_features"]))
    frame = read_dataset(source)
    batch = build_monitoring_batch(
        frame,
        features=features,
        mode=args.mode,
        drift_features=args.drift_features,
        shift_sigma=args.shift_sigma,
    )
    write_dataset(batch, args.output)
    print(f"monitoring_batch={args.output}")
    print(f"mode={args.mode}")
    print(f"rows={len(batch)}")


if __name__ == "__main__":
    main()
