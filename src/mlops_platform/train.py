"""Train a model, persist native artifacts, and record the experiment in MLflow."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import joblib
import mlflow
import mlflow.sklearn
from mlflow.models import infer_signature
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from mlops_platform import __version__
from mlops_platform.data import feature_columns, load_config, read_dataset
from mlops_platform.monitoring import build_reference_profile, write_reference_profile
from mlops_platform.tracking import resolve_tracking_uri


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fit_and_evaluate(
    config: dict[str, Any],
    dataset_path: Path,
) -> tuple[Pipeline, dict[str, float], Any, Any]:
    seed = int(config["seed"])
    n_features = int(config["dataset"]["n_features"])
    frame = read_dataset(dataset_path)
    features = feature_columns(n_features)
    x = frame[features]
    y = frame["target"]

    x_train, x_test, y_train, y_test = train_test_split(
        x,
        y,
        test_size=float(config["split"]["test_size"]),
        random_state=seed,
        stratify=y,
    )

    model = Pipeline(
        steps=[
            ("scale", StandardScaler()),
            (
                "classifier",
                LogisticRegression(
                    C=float(config["model"]["C"]),
                    max_iter=int(config["model"]["max_iter"]),
                    random_state=seed,
                ),
            ),
        ]
    )
    model.fit(x_train, y_train)

    probability = model.predict_proba(x_test)[:, 1]
    prediction = (probability >= 0.5).astype(int)
    metrics = {
        "roc_auc": float(roc_auc_score(y_test, probability)),
        "accuracy": float(accuracy_score(y_test, prediction)),
        "f1": float(f1_score(y_test, prediction)),
    }
    return model, metrics, x_train, x_test


def _log_mlflow_run(
    *,
    config: dict[str, Any],
    config_path: Path,
    dataset_path: Path,
    model: Pipeline,
    metrics: dict[str, float],
    x_train: Any,
    x_test: Any,
    artifact_dir: Path,
    model_path: Path,
    dataset_sha256: str,
) -> dict[str, str]:
    settings = config["mlflow"]
    mlflow.set_tracking_uri(resolve_tracking_uri(config))
    mlflow.set_experiment(str(settings["experiment_name"]))

    with mlflow.start_run(run_name=str(settings["run_name"])) as run:
        mlflow.log_params(
            {
                "seed": int(config["seed"]),
                "test_size": float(config["split"]["test_size"]),
                "n_features": int(config["dataset"]["n_features"]),
                "dataset_rows": int(len(x_train) + len(x_test)),
                "model_C": float(config["model"]["C"]),
                "model_max_iter": int(config["model"]["max_iter"]),
            }
        )
        mlflow.log_metrics(metrics)
        mlflow.set_tags(
            {
                "project": "mlops-platform",
                "project.version": __version__,
                "dataset.sha256": dataset_sha256,
                "data.contract": "strict_binary_classification_v1",
                "model.family": "sklearn.LogisticRegression",
            }
        )

        input_example = x_test.head(5)
        signature = infer_signature(input_example, model.predict_proba(input_example))
        model_info = mlflow.sklearn.log_model(
            sk_model=model,
            name="model",
            signature=signature,
            input_example=input_example,
        )

        mlflow.log_artifact(str(config_path), artifact_path="inputs")
        manifest_path = artifact_dir / "data_manifest.json"
        validation_path = artifact_dir / "data_validation.json"
        if manifest_path.exists():
            mlflow.log_artifact(str(manifest_path), artifact_path="inputs")
        if validation_path.exists():
            mlflow.log_artifact(str(validation_path), artifact_path="inputs")
        reference_profile_path = artifact_dir / "reference_profile.json"
        if reference_profile_path.exists():
            mlflow.log_artifact(str(reference_profile_path), artifact_path="monitoring")

        run_info = {
            "run_id": run.info.run_id,
            "experiment_id": run.info.experiment_id,
            "tracking_uri": mlflow.get_tracking_uri(),
            "artifact_uri": mlflow.get_artifact_uri(),
            "model_uri": model_info.model_uri,
            "model_id": model_info.model_id or "",
        }
        run_path = artifact_dir / "mlflow_run.json"
        run_path.write_text(
            json.dumps(run_info, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        mlflow.log_artifact(str(run_path), artifact_path="run_metadata")
        mlflow.log_artifact(str(model_path), artifact_path="native_model")
        return run_info


def train(
    config_path: Path,
    data_path: Path | None = None,
    *,
    enable_tracking: bool | None = None,
) -> dict[str, float]:
    config: dict[str, Any] = load_config(config_path)
    n_features = int(config["dataset"]["n_features"])
    dataset_path = data_path or Path(config["paths"]["dataset"])
    artifact_dir = Path(config["paths"]["artifact_dir"])
    artifact_dir.mkdir(parents=True, exist_ok=True)

    model, metrics, x_train, x_test = _fit_and_evaluate(config, dataset_path)
    model_path = artifact_dir / "model.joblib"
    joblib.dump(model, model_path)

    dataset_sha256 = _sha256(dataset_path)
    reference_profile = build_reference_profile(
        x_train,
        features=feature_columns(n_features),
        dataset_sha256=dataset_sha256,
        bins=int(config.get("monitoring", {}).get("profile_bins", 10)),
    )
    write_reference_profile(reference_profile, artifact_dir / "reference_profile.json")

    (artifact_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    tracking_config = config.get("mlflow", {})
    tracking_enabled = (
        bool(tracking_config.get("enabled", False)) if enable_tracking is None else enable_tracking
    )
    run_info: dict[str, str] | None = None
    if tracking_enabled:
        run_info = _log_mlflow_run(
            config=config,
            config_path=config_path,
            dataset_path=dataset_path,
            model=model,
            metrics=metrics,
            x_train=x_train,
            x_test=x_test,
            artifact_dir=artifact_dir,
            model_path=model_path,
            dataset_sha256=dataset_sha256,
        )

    metadata = {
        "project_version": __version__,
        "seed": int(config["seed"]),
        "n_features": n_features,
        "train_rows": int(len(x_train)),
        "test_rows": int(len(x_test)),
        "dataset_path": dataset_path.as_posix(),
        "dataset_sha256": dataset_sha256,
        "model_sha256": _sha256(model_path),
        "mlflow": run_info,
        "config": config,
    }
    metadata_path = artifact_dir / "model_meta.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if run_info is not None:
        mlflow.set_tracking_uri(resolve_tracking_uri(config))
        with mlflow.start_run(run_id=run_info["run_id"]):
            mlflow.log_artifact(str(metadata_path), artifact_path="run_metadata")
            mlflow.log_artifact(str(artifact_dir / "metrics.json"), artifact_path="run_metadata")

    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/train.yaml"))
    parser.add_argument("--data", type=Path)
    parser.add_argument("--no-mlflow", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            train(args.config, args.data, enable_tracking=False if args.no_mlflow else None),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
