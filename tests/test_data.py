from pathlib import Path

import pandas as pd

from mlops_platform.data import DatasetConfig, build_dataframe, write_dataset


def _config() -> DatasetConfig:
    return DatasetConfig(200, 10, 6, 2, 1.0)


def test_dataset_is_deterministic() -> None:
    pd.testing.assert_frame_equal(
        build_dataframe(_config(), seed=42),
        build_dataframe(_config(), seed=42),
    )


def test_written_dataset_is_byte_stable(tmp_path: Path) -> None:
    frame = build_dataframe(_config(), seed=42)
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    write_dataset(frame, first)
    write_dataset(frame, second)
    assert first.read_bytes() == second.read_bytes()
