from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FIRST_PARTY_WORKLOADS = {
    "api": ROOT / "k8s/base/api.yaml",
    "mlflow": ROOT / "k8s/base/mlflow.yaml",
    "kafka-consumer": ROOT / "k8s/base/kafka-consumer.yaml",
    "model-bootstrap": ROOT / "k8s/base/bootstrap-job.yaml",
    "kafka-topic-init": ROOT / "k8s/base/kafka-init-job.yaml",
}


def _documents(path: Path) -> list[dict]:
    return [doc for doc in yaml.safe_load_all(path.read_text()) if doc]


def _workload(path: Path, name: str) -> dict:
    for doc in _documents(path):
        if doc.get("kind") not in {"Deployment", "Job"}:
            continue
        if doc["metadata"]["name"] == name:
            return doc
    raise AssertionError(f"workload not found: {name}")


def _check_container(container: dict, workload_name: str) -> None:
    if not str(container.get("image", "")).startswith("mlops-platform:"):
        return
    context = container.get("securityContext", {})
    assert context.get("runAsNonRoot") is True, workload_name
    assert context.get("runAsUser") == 10001, workload_name
    assert context.get("runAsGroup") == 10001, workload_name
    assert context.get("allowPrivilegeEscalation") is False, workload_name
    assert "ALL" in context.get("capabilities", {}).get("drop", []), workload_name


def validate_kubernetes() -> None:
    for name, path in FIRST_PARTY_WORKLOADS.items():
        workload = _workload(path, name)
        pod = workload["spec"]["template"]["spec"]
        assert pod.get("automountServiceAccountToken") is False, name
        profile = pod.get("securityContext", {}).get("seccompProfile", {}).get("type")
        assert profile == "RuntimeDefault", name
        for container in pod.get("containers", []):
            _check_container(container, name)
        for container in pod.get("initContainers", []):
            _check_container(container, name)


def validate_dockerfile() -> None:
    text = (ROOT / "Dockerfile").read_text()
    assert "USER app" in text
    assert "HEALTHCHECK" in text
    assert "--uid 10001" in text
    assert "FROM python:3.12-slim@sha256:" in text


def validate_ci() -> None:
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    release = (ROOT / ".github/workflows/release.yml").read_text()
    dependabot = (ROOT / ".github/dependabot.yml").read_text()

    assert "permissions:\n  contents: read" in ci
    assert "aquasecurity/trivy-action@v0.36.0" in ci
    assert "version: v0.73.0" in ci
    assert "severity: CRITICAL" in ci
    assert "docker/build-push-action@v7.2.0" in ci

    assert "packages: write" in release
    assert "id-token: write" in release
    assert "provenance: mode=max" in release
    assert "sbom: true" in release
    assert "sigstore/cosign-installer@v4.1.2" in release
    assert "cosign sign --yes" in release
    assert "cosign verify" in release

    assert "package-ecosystem: pip" in dependabot
    assert "package-ecosystem: github-actions" in dependabot


def main() -> int:
    validate_dockerfile()
    validate_kubernetes()
    validate_ci()
    print("M11 security + supply-chain contracts: PASSED")
    print("container_user=app")
    print("seccomp_profile=RuntimeDefault")
    print("service_account_token_automount=false")
    print("trivy_version=v0.73.0")
    print("release_signing=cosign-keyless")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"security validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
