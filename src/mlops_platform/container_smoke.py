"""Smoke test the Docker Compose API from the host."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from mlops_platform import __version__
from mlops_platform.data import feature_columns, load_config


def _request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 3.0,
) -> tuple[int, dict[str, Any]]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data is not None else {}
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8"))
        return exc.code, body


def _wait_ready(base_url: str, wait_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + wait_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            status_code, payload = _request_json("GET", f"{base_url}/ready")
            if status_code == 200 and payload.get("status") == "ready":
                return payload
        except (OSError, ValueError) as exc:
            last_error = exc
        time.sleep(1.0)
    raise RuntimeError(f"API did not become ready within {wait_seconds:g}s") from last_error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/train.yaml"))
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--wait-seconds", type=float, default=120.0)
    args = parser.parse_args()

    config = load_config(args.config)
    expected_alias = str(config["serving"]["model_alias"])
    expected_model_name = str(config["registry"]["model_name"])
    n_features = int(config["dataset"]["n_features"])
    base_url = args.base_url.rstrip("/")
    ready = _wait_ready(base_url, args.wait_seconds)

    health_code, health = _request_json("GET", f"{base_url}/health")
    info_code, info = _request_json("GET", f"{base_url}/v1/model-info")
    features = {name: 0.0 for name in feature_columns(n_features)}
    prediction_code, prediction = _request_json(
        "POST",
        f"{base_url}/v1/predict",
        {"features": features},
    )

    assert health_code == 200, health
    assert info_code == 200, info
    assert prediction_code == 200, prediction
    assert health["project_version"] == __version__
    assert ready["model_alias"] == expected_alias
    assert ready["model_name"] == expected_model_name
    assert info["alias"] == expected_alias
    assert info["model_name"] == expected_model_name
    assert prediction["model_version"] == info["version"]
    assert 0.0 <= float(prediction["probability"]) <= 1.0

    print("Docker Compose M5 smoke: PASSED")
    print(f"project_version={health['project_version']}")
    print(f"model_uri={info['model_uri']}")
    print(f"model_version={info['version']}")
    print(f"run_id={info['run_id']}")
    print(f"probability={float(prediction['probability']):.6f}")


if __name__ == "__main__":
    main()
