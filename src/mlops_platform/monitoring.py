"""Batch data-quality and distribution-drift monitoring with retraining decisions."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import mlflow
import numpy as np
import pandas as pd

from mlops_platform import __version__
from mlops_platform.data import load_config, read_dataset
from mlops_platform.tracking import resolve_tracking_uri

_EPSILON = 1e-6


@dataclass(frozen=True)
class RetrainingDecision:
    action: str
    retrain_required: bool
    reason: str
    data_quality_status: str
    drift_status: str
    batch_rows: int
    drifted_features: int
    drifted_feature_ratio: float
    max_psi: float
    max_missing_ratio: float
    max_non_finite_ratio: float
    max_outside_reference_ratio: float


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite_values(series: pd.Series) -> np.ndarray:
    numeric = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    return numeric[np.isfinite(numeric)]


def _quantile_edges(values: np.ndarray, bins: int) -> list[float]:
    if values.size == 0:
        raise ValueError("reference feature contains no finite values")
    quantiles = np.linspace(0.0, 1.0, bins + 1)[1:-1]
    edges = np.unique(np.quantile(values, quantiles))
    return [float(value) for value in edges]


def _distribution(values: np.ndarray, edges: list[float]) -> list[float]:
    boundaries = np.asarray([-np.inf, *edges, np.inf], dtype=float)
    counts, _ = np.histogram(values, bins=boundaries)
    smoothed = counts.astype(float) + _EPSILON
    proportions = smoothed / smoothed.sum()
    return [float(value) for value in proportions]


def build_reference_profile(
    frame: pd.DataFrame,
    *,
    features: list[str],
    dataset_sha256: str,
    bins: int,
) -> dict[str, Any]:
    """Build a deterministic numeric reference profile for batch monitoring."""
    feature_profiles: dict[str, dict[str, Any]] = {}
    for name in features:
        values = _finite_values(frame[name])
        edges = _quantile_edges(values, bins)
        feature_profiles[name] = {
            "mean": float(values.mean()),
            "std": float(values.std(ddof=0)),
            "min": float(values.min()),
            "max": float(values.max()),
            "bin_edges": edges,
            "expected_proportions": _distribution(values, edges),
        }

    return {
        "profile_version": "numeric_psi_v1",
        "project_version": __version__,
        "dataset_sha256": dataset_sha256,
        "reference_role": "model_training_features",
        "rows": int(len(frame)),
        "features": feature_profiles,
        "requested_bins": int(bins),
    }


def write_reference_profile(profile: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(profile, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _psi(actual_values: np.ndarray, feature_profile: dict[str, Any]) -> float:
    expected = np.asarray(feature_profile["expected_proportions"], dtype=float)
    actual = np.asarray(
        _distribution(actual_values, list(feature_profile["bin_edges"])),
        dtype=float,
    )
    expected = np.clip(expected, _EPSILON, None)
    actual = np.clip(actual, _EPSILON, None)
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def evaluate_batch(
    batch: pd.DataFrame,
    reference_profile: dict[str, Any],
    monitoring_config: dict[str, Any],
) -> tuple[dict[str, Any], RetrainingDecision]:
    """Compare a production batch with a reference profile and apply policy."""
    required_features = list(reference_profile["features"])
    missing_columns = sorted(set(required_features) - set(batch.columns))
    row_count = int(len(batch))

    feature_reports: dict[str, dict[str, float]] = {}
    max_missing_ratio = 0.0
    max_non_finite_ratio = 0.0
    max_outside_ratio = 0.0
    max_psi = 0.0
    drifted_features = 0

    if not missing_columns:
        for name in required_features:
            numeric_series = pd.to_numeric(batch[name], errors="coerce")
            numeric = numeric_series.to_numpy(dtype=float)
            original_missing = pd.isna(batch[name]).to_numpy()
            missing_ratio = float(original_missing.mean())
            non_finite_mask = ~np.isfinite(numeric) & ~original_missing
            non_finite_ratio = float(non_finite_mask.mean())
            finite = numeric[np.isfinite(numeric)]
            profile = reference_profile["features"][name]

            if finite.size:
                psi = _psi(finite, profile)
                outside_ratio = float(
                    np.mean((finite < float(profile["min"])) | (finite > float(profile["max"])))
                )
                mean_shift_std = abs(float(finite.mean()) - float(profile["mean"])) / max(
                    float(profile["std"]), _EPSILON
                )
            else:
                psi = 0.0
                outside_ratio = 0.0
                mean_shift_std = 0.0

            if psi >= float(monitoring_config["psi_retrain_threshold"]):
                drifted_features += 1

            max_missing_ratio = max(max_missing_ratio, missing_ratio)
            max_non_finite_ratio = max(max_non_finite_ratio, non_finite_ratio)
            max_outside_ratio = max(max_outside_ratio, outside_ratio)
            max_psi = max(max_psi, psi)
            feature_reports[name] = {
                "psi": float(psi),
                "missing_ratio": missing_ratio,
                "non_finite_ratio": non_finite_ratio,
                "outside_reference_ratio": outside_ratio,
                "mean_shift_std": float(mean_shift_std),
            }

    feature_count = max(len(required_features), 1)
    drifted_feature_ratio = drifted_features / feature_count
    quality_failed = bool(
        missing_columns
        or row_count < int(monitoring_config["min_batch_rows"])
        or max_missing_ratio > float(monitoring_config["max_missing_ratio"])
        or max_non_finite_ratio > float(monitoring_config["max_non_finite_ratio"])
    )
    retrain_due_to_psi = drifted_feature_ratio >= float(
        monitoring_config["drifted_feature_ratio_threshold"]
    )
    retrain_due_to_range = max_outside_ratio >= float(
        monitoring_config["outside_reference_ratio_threshold"]
    )

    if quality_failed:
        action = "investigate"
        retrain_required = False
        reason = "data_quality_gate_failed"
        data_quality_status = "failed"
        drift_status = "not_evaluated" if missing_columns else "observed"
    elif retrain_due_to_psi or retrain_due_to_range:
        action = "retrain"
        retrain_required = True
        reason = "distribution_drift_threshold_exceeded"
        data_quality_status = "passed"
        drift_status = "drifted"
    elif max_psi >= float(monitoring_config["psi_warning_threshold"]):
        action = "no_action"
        retrain_required = False
        reason = "drift_warning_below_retraining_policy"
        data_quality_status = "passed"
        drift_status = "warning"
    else:
        action = "no_action"
        retrain_required = False
        reason = "batch_within_reference_policy"
        data_quality_status = "passed"
        drift_status = "stable"

    decision = RetrainingDecision(
        action=action,
        retrain_required=retrain_required,
        reason=reason,
        data_quality_status=data_quality_status,
        drift_status=drift_status,
        batch_rows=row_count,
        drifted_features=drifted_features,
        drifted_feature_ratio=float(drifted_feature_ratio),
        max_psi=float(max_psi),
        max_missing_ratio=float(max_missing_ratio),
        max_non_finite_ratio=float(max_non_finite_ratio),
        max_outside_reference_ratio=float(max_outside_ratio),
    )
    report = {
        "monitoring_contract": "batch_numeric_drift_v1",
        "reference_dataset_sha256": reference_profile["dataset_sha256"],
        "batch_rows": row_count,
        "missing_columns": missing_columns,
        "feature_reports": feature_reports,
        "decision": asdict(decision),
    }
    return report, decision


def monitor_batch(
    *,
    config_path: Path,
    batch_path: Path,
    reference_profile_path: Path,
    report_path: Path,
    decision_path: Path,
    log_to_mlflow: bool = True,
) -> RetrainingDecision:
    config = load_config(config_path)
    monitoring_config = config["monitoring"]
    batch = read_dataset(batch_path)
    reference_profile = json.loads(reference_profile_path.read_text(encoding="utf-8"))
    report, decision = evaluate_batch(batch, reference_profile, monitoring_config)
    report["batch_sha256"] = _sha256_file(batch_path)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    decision_path.write_text(
        json.dumps(asdict(decision), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if log_to_mlflow:
        mlflow.set_tracking_uri(resolve_tracking_uri(config))
        mlflow.set_experiment(str(monitoring_config["experiment_name"]))
        with mlflow.start_run(run_name=str(monitoring_config["run_name"])):
            mlflow.log_metrics(
                {
                    "drifted_feature_ratio": decision.drifted_feature_ratio,
                    "max_psi": decision.max_psi,
                    "max_missing_ratio": decision.max_missing_ratio,
                    "max_non_finite_ratio": decision.max_non_finite_ratio,
                    "max_outside_reference_ratio": (decision.max_outside_reference_ratio),
                    "retrain_required": float(decision.retrain_required),
                }
            )
            mlflow.set_tags(
                {
                    "project": "mlops-platform",
                    "project.version": __version__,
                    "monitoring.contract": "batch_numeric_drift_v1",
                    "monitoring.action": decision.action,
                    "monitoring.reason": decision.reason,
                    "reference.dataset.sha256": str(reference_profile["dataset_sha256"]),
                    "batch.sha256": report["batch_sha256"],
                }
            )
            mlflow.log_artifact(str(report_path), artifact_path="monitoring")
            mlflow.log_artifact(str(decision_path), artifact_path="monitoring")

    return decision


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/train.yaml"))
    parser.add_argument(
        "--batch",
        type=Path,
        default=Path("data/monitoring/current_batch.csv"),
    )
    parser.add_argument("--reference-profile", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--decision", type=Path)
    parser.add_argument("--no-mlflow", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    artifact_dir = Path(config["paths"]["artifact_dir"])
    reference_profile = args.reference_profile or artifact_dir / "reference_profile.json"
    report_path = args.report or artifact_dir / "drift_report.json"
    decision_path = args.decision or artifact_dir / "retraining_decision.json"
    decision = monitor_batch(
        config_path=args.config,
        batch_path=args.batch,
        reference_profile_path=reference_profile,
        report_path=report_path,
        decision_path=decision_path,
        log_to_mlflow=not args.no_mlflow,
    )
    print(json.dumps(asdict(decision), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
