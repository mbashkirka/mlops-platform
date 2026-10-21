"""Strict data contract and validation artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pandera.pandas as pa

from mlops_platform.data import feature_columns, load_config, read_dataset


def build_schema(n_features: int) -> pa.DataFrameSchema:
    columns: dict[str, pa.Column] = {"row_id": pa.Column(int, nullable=False, unique=True)}
    columns.update({name: pa.Column(float, nullable=False) for name in feature_columns(n_features)})
    columns["target"] = pa.Column(
        int,
        checks=pa.Check.isin([0, 1]),
        nullable=False,
    )
    return pa.DataFrameSchema(
        columns=columns,
        strict=True,
        ordered=True,
        coerce=False,
        unique_column_names=True,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_frame(
    frame: pd.DataFrame,
    *,
    expected_rows: int,
    n_features: int,
) -> dict[str, Any]:
    build_schema(n_features).validate(frame, lazy=True)

    if len(frame) != expected_rows:
        raise ValueError(f"row count mismatch: expected {expected_rows}, got {len(frame)}")

    expected_ids = pd.RangeIndex(start=0, stop=expected_rows, step=1)
    if not pd.Index(frame["row_id"]).equals(expected_ids):
        raise ValueError("row_id must be contiguous, ordered, and start at zero")

    class_counts = {
        str(int(label)): int(count)
        for label, count in frame["target"].value_counts().sort_index().items()
    }
    if set(class_counts) != {"0", "1"}:
        raise ValueError("both target classes must be present")

    return {
        "status": "passed",
        "rows": int(len(frame)),
        "columns": int(frame.shape[1]),
        "features": int(n_features),
        "missing_values": int(frame.isna().sum().sum()),
        "duplicate_row_ids": int(frame["row_id"].duplicated().sum()),
        "class_counts": class_counts,
        "target_rate": float(frame["target"].mean()),
    }


def validate_dataset(
    *,
    config_path: Path,
    input_path: Path,
    report_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    config = load_config(config_path)
    frame = read_dataset(input_path)
    validation = validate_frame(
        frame,
        expected_rows=int(config["dataset"]["n_samples"]),
        n_features=int(config["dataset"]["n_features"]),
    )
    fingerprint = sha256_file(input_path)
    validation["dataset_sha256"] = fingerprint

    manifest = {
        "dataset_path": input_path.as_posix(),
        "dataset_sha256": fingerprint,
        "rows": validation["rows"],
        "features": validation["features"],
        "target_rate": validation["target_rate"],
        "seed": int(config["seed"]),
        "contract": "strict_binary_classification_v1",
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(validation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return validation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/train.yaml"))
    parser.add_argument("--input", type=Path, default=Path("data/raw/dataset.csv"))
    parser.add_argument("--report", type=Path, default=Path("artifacts/data_validation.json"))
    parser.add_argument("--manifest", type=Path, default=Path("artifacts/data_manifest.json"))
    args = parser.parse_args()

    result = validate_dataset(
        config_path=args.config,
        input_path=args.input,
        report_path=args.report,
        manifest_path=args.manifest,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
