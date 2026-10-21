from __future__ import annotations

import numpy as np
import pandas as pd

from mlops_platform.monitoring import build_reference_profile, evaluate_batch
from mlops_platform.monitoring_batch import build_monitoring_batch


def _config() -> dict[str, float | int]:
    return {
        "min_batch_rows": 100,
        "max_missing_ratio": 0.01,
        "max_non_finite_ratio": 0.0,
        "psi_warning_threshold": 0.10,
        "psi_retrain_threshold": 0.20,
        "drifted_feature_ratio_threshold": 0.25,
        "outside_reference_ratio_threshold": 0.15,
    }


def _reference_frame(rows: int = 1000) -> tuple[pd.DataFrame, list[str]]:
    rng = np.random.default_rng(42)
    features = [f"feature_{index:02d}" for index in range(4)]
    frame = pd.DataFrame({name: rng.normal(size=rows) for name in features})
    frame.insert(0, "row_id", np.arange(rows))
    return frame, features


def test_identical_batch_is_stable() -> None:
    frame, features = _reference_frame()
    profile = build_reference_profile(
        frame,
        features=features,
        dataset_sha256="a" * 64,
        bins=10,
    )
    batch = build_monitoring_batch(
        frame,
        features=features,
        mode="stable",
        drift_features=2,
        shift_sigma=3.0,
    )

    report, decision = evaluate_batch(batch, profile, _config())

    assert report["missing_columns"] == []
    assert decision.action == "no_action"
    assert decision.drift_status == "stable"
    assert decision.retrain_required is False
    assert decision.max_psi < 1e-8


def test_shifted_batch_triggers_retraining() -> None:
    frame, features = _reference_frame()
    profile = build_reference_profile(
        frame,
        features=features,
        dataset_sha256="b" * 64,
        bins=10,
    )
    batch = build_monitoring_batch(
        frame,
        features=features,
        mode="drifted",
        drift_features=2,
        shift_sigma=3.0,
    )

    _, decision = evaluate_batch(batch, profile, _config())

    assert decision.action == "retrain"
    assert decision.retrain_required is True
    assert decision.data_quality_status == "passed"
    assert decision.drifted_feature_ratio >= 0.25


def test_bad_data_quality_is_investigated_not_retrained() -> None:
    frame, features = _reference_frame()
    profile = build_reference_profile(
        frame,
        features=features,
        dataset_sha256="c" * 64,
        bins=10,
    )
    batch = frame[["row_id", *features]].copy()
    batch.loc[:100, features[0]] = np.nan

    _, decision = evaluate_batch(batch, profile, _config())

    assert decision.action == "investigate"
    assert decision.data_quality_status == "failed"
    assert decision.retrain_required is False
