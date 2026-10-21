from __future__ import annotations

import argparse
import os
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER_TAG = re.compile(r"^v(?P<version>0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def project_version() -> str:
    payload = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return str(payload["project"]["version"])


def validate_tag(tag: str) -> None:
    match = SEMVER_TAG.fullmatch(tag)
    if match is None:
        raise ValueError(f"release tag is not strict SemVer: {tag}")
    expected = f"v{project_version()}"
    if tag != expected:
        raise ValueError(f"release tag {tag} does not match project version {expected}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate release tag against pyproject.toml")
    parser.add_argument("--tag", default=os.getenv("GITHUB_REF_NAME"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.tag:
        raise ValueError("release tag is required via --tag or GITHUB_REF_NAME")
    validate_tag(args.tag)
    print("M11 release contract: PASSED")
    print(f"project_version={project_version()}")
    print(f"release_tag={args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
