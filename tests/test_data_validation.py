from pathlib import Path

import pandera.errors
import pytest

from mlops_platform.data import DatasetConfig, build_dataframe, write_dataset
from mlops_platform.data_validation import sha256_file, validate_frame


def _config() -> DatasetConfig:
    return DatasetConfig(100, 8, 5, 1, 1.0)


def test_valid_frame_passes_contract() -> None:
    result = validate_frame(
        build_dataframe(_config(), seed=42),
        expected_rows=100,
        n_features=8,
    )
    assert result["status"] == "passed"
    assert result["missing_values"] == 0
    assert result["duplicate_row_ids"] == 0


def test_contract_rejects_invalid_target() -> None:
    frame = build_dataframe(_config(), seed=42)
    frame.loc[0, "target"] = 7
    with pytest.raises(pandera.errors.SchemaErrors):
        validate_frame(frame, expected_rows=100, n_features=8)


def test_contract_rejects_unexpected_column() -> None:
    frame = build_dataframe(_config(), seed=42)
    frame["leaked_feature"] = 1.0
    with pytest.raises(pandera.errors.SchemaErrors):
        validate_frame(frame, expected_rows=100, n_features=8)


def test_fingerprint_changes_with_content(tmp_path: Path) -> None:
    frame = build_dataframe(_config(), seed=42)
    path = tmp_path / "dataset.csv"
    write_dataset(frame, path)
    before = sha256_file(path)
    frame.loc[0, "feature_00"] += 1.0
    write_dataset(frame, path)
    assert before != sha256_file(path)
