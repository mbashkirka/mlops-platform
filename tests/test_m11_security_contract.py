from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _docs(path: str) -> list[dict]:
    payload = (ROOT / path).read_text()
    return [doc for doc in yaml.safe_load_all(payload) if doc]


def _workload(path: str, name: str) -> dict:
    return next(
        doc
        for doc in _docs(path)
        if doc.get("kind") in {"Deployment", "Job"} and doc["metadata"]["name"] == name
    )


def test_first_party_workloads_disable_service_account_tokens_and_use_seccomp() -> None:
    targets = {
        "k8s/base/api.yaml": "api",
        "k8s/base/mlflow.yaml": "mlflow",
        "k8s/base/kafka-consumer.yaml": "kafka-consumer",
        "k8s/base/bootstrap-job.yaml": "model-bootstrap",
        "k8s/base/kafka-init-job.yaml": "kafka-topic-init",
    }
    for path, name in targets.items():
        spec = _workload(path, name)["spec"]["template"]["spec"]
        assert spec["automountServiceAccountToken"] is False
        assert spec["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"


def test_first_party_containers_are_non_root_without_linux_capabilities() -> None:
    targets = {
        "k8s/base/api.yaml": "api",
        "k8s/base/mlflow.yaml": "mlflow",
        "k8s/base/kafka-consumer.yaml": "kafka-consumer",
        "k8s/base/bootstrap-job.yaml": "model-bootstrap",
        "k8s/base/kafka-init-job.yaml": "kafka-topic-init",
    }
    for path, name in targets.items():
        spec = _workload(path, name)["spec"]["template"]["spec"]
        containers = spec.get("containers", []) + spec.get("initContainers", [])
        for container in containers:
            if not container["image"].startswith("mlops-platform:"):
                continue
            context = container["securityContext"]
            assert context["runAsNonRoot"] is True
            assert context["allowPrivilegeEscalation"] is False
            assert "ALL" in context["capabilities"]["drop"]


def test_ci_and_release_workflows_have_supply_chain_gates() -> None:
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    release = (ROOT / ".github/workflows/release.yml").read_text()

    assert "aquasecurity/trivy-action@v0.36.0" in ci
    assert "version: v0.73.0" in ci
    assert "severity: CRITICAL" in ci
    assert "provenance: mode=max" in release
    assert "sbom: true" in release
    assert "mlops-platform:release-candidate" in release
    assert "version: v0.73.0" in release
    assert "cosign sign --yes" in release
    assert "cosign verify" in release


def test_release_tag_must_match_project_version() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/release_validate.py", "--tag", "v1.0.0"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "M11 release contract: PASSED" in result.stdout


def test_security_validation_script_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/security_validate.py"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "M11 security + supply-chain contracts: PASSED" in result.stdout


def test_application_base_image_is_digest_pinned() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "FROM python:3.12-slim@sha256:" in dockerfile
