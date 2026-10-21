from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
K8S_ROOT = ROOT / "k8s"


def main() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = str(pyproject["project"]["version"])
    manifests = sorted(K8S_ROOT.rglob("*.yaml"))
    resource_count = 0

    for path in manifests:
        documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        for document in documents:
            if not document:
                continue
            if path.name == "kind-config.yaml" or document.get("kind") == "Kustomization":
                continue
            assert document.get("apiVersion"), path
            assert document.get("kind"), path
            assert document.get("metadata", {}).get("name"), path
            resource_count += 1

    expected_image = f"mlops-platform:{version}"
    for path in (K8S_ROOT / "base").glob("*.yaml"):
        if path.name == "secret.example.yaml":
            continue
        text = path.read_text(encoding="utf-8")
        if "mlops-platform:" in text:
            assert expected_image in text, path

    print("Kubernetes M10 manifests: syntax PASSED")
    print(f"project_version={version}")
    print(f"manifest_files={len(manifests)}")
    print(f"resources={resource_count}")


if __name__ == "__main__":
    main()
