from __future__ import annotations

from typing import Any

import mlflow

from mlops_platform.tracking import resolve_tracking_uri


def test_registry_smoke_tracking_uri_prefers_environment(monkeypatch: Any) -> None:
    config = {"mlflow": {"tracking_uri": "sqlite:///local.db"}}
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")

    tracking_uri = resolve_tracking_uri(config)
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_registry_uri(tracking_uri)

    assert mlflow.get_tracking_uri() == "http://mlflow:5000"
    assert mlflow.get_registry_uri() == "http://mlflow:5000"
