"""Register MLflow models and govern candidate-to-champion promotion."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import mlflow
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from mlops_platform import __version__
from mlops_platform.data import load_config
from mlops_platform.tracking import resolve_tracking_uri


@dataclass(frozen=True)
class PromotionDecision:
    model_name: str
    candidate_version: str
    candidate_roc_auc: float
    previous_champion_version: str | None
    previous_champion_roc_auc: float | None
    min_roc_auc: float
    min_improvement: float
    promoted: bool
    reason: str


def _configure_mlflow(config: dict[str, Any]) -> MlflowClient:
    tracking_uri = resolve_tracking_uri(config)
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_registry_uri(tracking_uri)
    return MlflowClient(tracking_uri=tracking_uri, registry_uri=tracking_uri)


def _get_alias_or_none(
    client: MlflowClient,
    model_name: str,
    alias: str,
):
    try:
        return client.get_model_version_by_alias(model_name, alias)
    except MlflowException:
        return None


def _metric_for_version(client: MlflowClient, model_version: Any, metric: str) -> float:
    if not model_version.run_id:
        raise RuntimeError(f"model version {model_version.version} has no source run")
    run = client.get_run(model_version.run_id)
    if metric not in run.data.metrics:
        raise RuntimeError(f"source run {model_version.run_id} has no metric: {metric}")
    return float(run.data.metrics[metric])


def evaluate_promotion(
    *,
    candidate_roc_auc: float,
    champion_roc_auc: float | None,
    min_roc_auc: float,
    min_improvement: float,
) -> tuple[bool, str]:
    """Apply the deterministic quality policy used by the registry workflow."""
    if candidate_roc_auc < min_roc_auc:
        return False, "candidate_below_min_roc_auc"
    if champion_roc_auc is None:
        return True, "first_qualified_champion"
    if candidate_roc_auc < champion_roc_auc + min_improvement:
        return False, "candidate_does_not_meet_champion_improvement"
    return True, "candidate_meets_promotion_policy"


def register_and_promote(
    config_path: Path,
    run_info_path: Path | None = None,
    decision_path: Path | None = None,
) -> PromotionDecision:
    """Register the latest logged model, mark it candidate, and evaluate promotion."""
    config = load_config(config_path)
    artifact_dir = Path(config["paths"]["artifact_dir"])
    run_info_path = run_info_path or artifact_dir / "mlflow_run.json"
    decision_path = decision_path or artifact_dir / "registry_decision.json"

    run_info = json.loads(run_info_path.read_text(encoding="utf-8"))
    run_id = str(run_info["run_id"])
    model_uri = str(run_info.get("model_uri") or f"runs:/{run_id}/model")

    settings = config["registry"]
    model_name = str(settings["model_name"])
    candidate_alias = str(settings["candidate_alias"])
    champion_alias = str(settings["champion_alias"])
    min_roc_auc = float(settings["min_roc_auc"])
    min_improvement = float(settings.get("min_improvement", 0.0))

    client = _configure_mlflow(config)
    previous_champion = _get_alias_or_none(client, model_name, champion_alias)
    previous_champion_auc = (
        _metric_for_version(client, previous_champion, "roc_auc")
        if previous_champion is not None
        else None
    )

    candidate = mlflow.register_model(
        model_uri=model_uri,
        name=model_name,
        tags={
            "project.version": __version__,
            "validation_status": "pending",
            "source.run_id": run_id,
        },
    )
    candidate_version = str(candidate.version)
    candidate_auc = _metric_for_version(client, candidate, "roc_auc")

    source_run = client.get_run(run_id)
    dataset_sha = source_run.data.tags.get("dataset.sha256", "")
    client.set_model_version_tag(model_name, candidate_version, "dataset.sha256", dataset_sha)
    client.set_model_version_tag(
        model_name,
        candidate_version,
        "roc_auc",
        f"{candidate_auc:.12f}",
    )
    client.set_registered_model_alias(model_name, candidate_alias, candidate_version)

    promoted, reason = evaluate_promotion(
        candidate_roc_auc=candidate_auc,
        champion_roc_auc=previous_champion_auc,
        min_roc_auc=min_roc_auc,
        min_improvement=min_improvement,
    )

    if promoted:
        if previous_champion is not None and str(previous_champion.version) != candidate_version:
            client.set_model_version_tag(
                model_name,
                str(previous_champion.version),
                "promotion_status",
                "superseded",
            )
        client.set_registered_model_alias(model_name, champion_alias, candidate_version)
        client.set_model_version_tag(model_name, candidate_version, "validation_status", "passed")
        client.set_model_version_tag(model_name, candidate_version, "promotion_status", "champion")
    else:
        client.set_model_version_tag(model_name, candidate_version, "validation_status", "rejected")
        client.set_model_version_tag(model_name, candidate_version, "promotion_status", "candidate")

    decision = PromotionDecision(
        model_name=model_name,
        candidate_version=candidate_version,
        candidate_roc_auc=candidate_auc,
        previous_champion_version=(
            str(previous_champion.version) if previous_champion is not None else None
        ),
        previous_champion_roc_auc=previous_champion_auc,
        min_roc_auc=min_roc_auc,
        min_improvement=min_improvement,
        promoted=promoted,
        reason=reason,
    )
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.write_text(
        json.dumps(asdict(decision), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return decision


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/train.yaml"))
    parser.add_argument("--run-info", type=Path)
    parser.add_argument("--decision", type=Path)
    args = parser.parse_args()
    decision = register_and_promote(args.config, args.run_info, args.decision)
    print(json.dumps(asdict(decision), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
