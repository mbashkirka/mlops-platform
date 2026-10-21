"""Dataset materialization and loading utilities."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from sklearn.datasets import make_classification


@dataclass(frozen=True)
class DatasetConfig:
    n_samples: int
    n_features: int
    n_informative: int
    n_redundant: int
    class_sep: float


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def feature_columns(n_features: int) -> list[str]:
    return [f"feature_{index:02d}" for index in range(n_features)]


def build_dataframe(config: DatasetConfig, *, seed: int) -> pd.DataFrame:
    x, y = make_classification(
        n_samples=config.n_samples,
        n_features=config.n_features,
        n_informative=config.n_informative,
        n_redundant=config.n_redundant,
        n_classes=2,
        class_sep=config.class_sep,
        random_state=seed,
    )
    frame = pd.DataFrame(x, columns=feature_columns(config.n_features), dtype=np.float64)
    frame.insert(0, "row_id", np.arange(config.n_samples, dtype=np.int64))
    frame["target"] = y.astype(np.int64)
    return frame


def write_dataset(frame: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False, float_format="%.17g")


def read_dataset(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/train.yaml"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    config = load_config(args.config)
    dataset_config = DatasetConfig(**config["dataset"])
    output = args.output or Path(config["paths"]["dataset"])
    frame = build_dataframe(dataset_config, seed=int(config["seed"]))
    write_dataset(frame, output)

    print(f"dataset={output}")
    print(f"rows={len(frame)}")
    print(f"features={dataset_config.n_features}")


if __name__ == "__main__":
    main()
