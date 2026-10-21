"""Shared MLflow endpoint resolution for local and container workflows."""

from __future__ import annotations

import os
from typing import Any


def resolve_tracking_uri(config: dict[str, Any]) -> str:
    """Prefer the deployment environment over the local YAML default."""
    return os.getenv("MLFLOW_TRACKING_URI", str(config["mlflow"]["tracking_uri"]))
