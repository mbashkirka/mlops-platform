from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DOCS = (
    Path("README.md"),
    Path("CHANGELOG.md"),
    Path("SECURITY.md"),
    Path("docs/ARCHITECTURE.md"),
    Path("docs/DEMO.md"),
    Path("docs/RUNBOOK.md"),
    Path("docs/PUBLISHING.md"),
)


def project_version() -> str:
    payload = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(payload["project"]["version"])


def validate_docs() -> None:
    for relative in REQUIRED_DOCS:
        path = ROOT / relative
        assert path.is_file(), f"missing release document: {relative}"
        assert path.stat().st_size > 200, f"release document is unexpectedly small: {relative}"

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "# MLOps Platform" in readme
    assert "make portfolio-demo" in readme
    assert "Current release candidate: **v1.0.0**" in readme
    assert "| M12 | Portfolio release + architecture + demo + runbook | done |" in readme

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [1.0.0]" in changelog

    for relative in REQUIRED_DOCS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "TODO" not in text
        assert "FIXME" not in text


def validate_automation() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    for target in ("portfolio-config:", "portfolio-demo:", "m12-smoke:", "release-ready:"):
        assert target in makefile, f"missing Makefile target: {target}"

    demo = (ROOT / "scripts/portfolio_demo.sh").read_text(encoding="utf-8")
    assert "make k8s-smoke" in demo
    assert "M12 portfolio demo: READY" in demo

    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "SBOM" not in release or "sbom: true" in release
    assert "sbom: true" in release
    assert "provenance: mode=max" in release
    assert "cosign sign --yes" in release


def main() -> int:
    assert project_version() == "1.0.0", "M12 release version must be 1.0.0"
    validate_docs()
    validate_automation()
    print("M12 portfolio release contracts: PASSED")
    print(f"project_version={project_version()}")
    print("roadmap_status=complete")
    print(f"release_documents={len(REQUIRED_DOCS)}")
    print("demo_target=portfolio-demo")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"portfolio validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
