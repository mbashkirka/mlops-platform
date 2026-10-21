from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _version() -> str:
    payload = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(payload["project"]["version"])


def test_m12_is_v1_release() -> None:
    assert _version() == "1.0.0"


def test_final_release_documents_exist() -> None:
    required = (
        "README.md",
        "CHANGELOG.md",
        "SECURITY.md",
        "docs/ARCHITECTURE.md",
        "docs/DEMO.md",
        "docs/RUNBOOK.md",
        "docs/PUBLISHING.md",
    )
    for relative in required:
        assert (ROOT / relative).is_file()


def test_roadmap_is_complete() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "| M12 | Portfolio release + architecture + demo + runbook | done |" in readme
    assert "Current release candidate: **v1.0.0**" in readme


def test_portfolio_validation_script_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/portfolio_validate.py"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "M12 portfolio release contracts: PASSED" in result.stdout


def test_makefile_exposes_final_release_targets() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "portfolio-config:" in makefile
    assert "portfolio-demo:" in makefile
    assert "m12-smoke:" in makefile
    assert "release-ready:" in makefile


def test_portfolio_demo_reuses_validated_kubernetes_smoke() -> None:
    script = (ROOT / "scripts/portfolio_demo.sh").read_text(encoding="utf-8")
    assert "make k8s-smoke" in script
    assert "http://127.0.0.1:8002/ready" in script
    assert "M12 portfolio demo: READY" in script


def test_changelog_records_all_milestones() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    for milestone in range(13):
        assert f"| M{milestone} |" in changelog
