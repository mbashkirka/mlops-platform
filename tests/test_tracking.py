from mlops_platform.tracking import resolve_tracking_uri


def test_tracking_uri_uses_config_by_default(monkeypatch) -> None:
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    config = {"mlflow": {"tracking_uri": "sqlite:///local.db"}}

    assert resolve_tracking_uri(config) == "sqlite:///local.db"


def test_tracking_uri_prefers_environment(monkeypatch) -> None:
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
    config = {"mlflow": {"tracking_uri": "sqlite:///local.db"}}

    assert resolve_tracking_uri(config) == "http://mlflow:5000"
