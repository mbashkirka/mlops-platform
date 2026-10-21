"""Load and execute the promoted MLflow Registry model for online serving."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from mlops_platform.data import feature_columns, load_config
from mlops_platform.tracking import resolve_tracking_uri


@dataclass(frozen=True)
class ModelIdentity:
    """Immutable identity and lineage of the model currently serving traffic."""

    model_name: str
    alias: str
    version: str
    run_id: str
    model_uri: str
    dataset_sha256: str
    roc_auc: float | None


@dataclass(frozen=True)
class ModelBundle:
    """Loaded estimator plus the serving contract required to execute it."""

    model: Any
    identity: ModelIdentity
    feature_names: tuple[str, ...]
    probability_threshold: float


def _optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def load_champion(config_path: Path) -> ModelBundle:
    """Resolve the configured champion alias and load that exact Registry model."""
    import mlflow
    import mlflow.sklearn
    from mlflow.tracking import MlflowClient

    config = load_config(config_path)
    tracking_uri = resolve_tracking_uri(config)
    model_name = str(config["registry"]["model_name"])
    alias = str(config.get("serving", {}).get("model_alias", config["registry"]["champion_alias"]))

    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_registry_uri(tracking_uri)
    client = MlflowClient(tracking_uri=tracking_uri, registry_uri=tracking_uri)
    version = client.get_model_version_by_alias(model_name, alias)

    model_uri = f"models:/{model_name}@{alias}"
    model = mlflow.sklearn.load_model(model_uri)
    n_features = int(config["dataset"]["n_features"])
    threshold = float(config.get("serving", {}).get("probability_threshold", 0.5))

    return ModelBundle(
        model=model,
        identity=ModelIdentity(
            model_name=model_name,
            alias=alias,
            version=str(version.version),
            run_id=str(version.run_id or ""),
            model_uri=model_uri,
            dataset_sha256=str(version.tags.get("dataset.sha256", "")),
            roc_auc=_optional_float(version.tags.get("roc_auc")),
        ),
        feature_names=tuple(feature_columns(n_features)),
        probability_threshold=threshold,
    )


def predict_probability(bundle: ModelBundle, features: dict[str, float]) -> float:
    """Run a single-row positive-class probability prediction."""
    frame = pd.DataFrame(
        [[features[name] for name in bundle.feature_names]],
        columns=bundle.feature_names,
    )
    return float(bundle.model.predict_proba(frame)[0, 1])
