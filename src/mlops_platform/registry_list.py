"""Inspect registered model versions and deployment aliases."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from mlops_platform.data import load_config
from mlops_platform.registry import _configure_mlflow


def aliases_by_version(alias_map: dict[str, str]) -> dict[str, list[str]]:
    """Invert the registered-model alias mapping for display by model version."""
    result: dict[str, list[str]] = defaultdict(list)
    for alias, version in alias_map.items():
        result[str(version)].append(str(alias))
    return {version: sorted(aliases) for version, aliases in result.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/train.yaml"))
    args = parser.parse_args()

    config = load_config(args.config)
    client = _configure_mlflow(config)
    model_name = str(config["registry"]["model_name"])
    versions = client.search_model_versions(f"name = '{model_name}'")
    if not versions:
        print(f"No registered versions found for: {model_name}")
        return

    registered_model = client.get_registered_model(model_name)
    version_aliases = aliases_by_version(registered_model.aliases)

    print("version  aliases              status      roc_auc       run_id")
    for version in sorted(versions, key=lambda item: int(item.version), reverse=True):
        aliases = ",".join(version_aliases.get(str(version.version), [])) or "-"
        status = version.tags.get("promotion_status", "-")
        roc_auc = version.tags.get("roc_auc", "-")
        run_id = version.run_id or "-"
        print(f"{version.version:>7}  {aliases:<19}  {status:<10}  {roc_auc:<12}  {run_id}")


if __name__ == "__main__":
    main()
