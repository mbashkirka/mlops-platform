#!/bin/sh
set -eu

PROJECT_VERSION="${PROJECT_VERSION:-1.0.0}"
IMAGE="mlops-platform:${PROJECT_VERSION}"

echo "[m11-smoke] validating release/security contracts"
python scripts/security_validate.py
python scripts/release_validate.py --tag "v${PROJECT_VERSION}"

echo "[m11-smoke] building hardened application image"
docker build --tag "${IMAGE}" .

container_user="$(docker inspect --format '{{.Config.User}}' "${IMAGE}")"
case "${container_user}" in
  app|10001|10001:10001) ;;
  *)
    echo "unexpected container user: ${container_user}" >&2
    exit 1
    ;;
esac

echo "container_user=${container_user}"

echo "[m11-smoke] scanning image for fixed critical vulnerabilities"
trivy image   --scanners vuln   --severity CRITICAL   --ignore-unfixed   --exit-code 1   --no-progress   "${IMAGE}"

echo "[m11-smoke] checking import/runtime identity"
docker run --rm --entrypoint python "${IMAGE}" -c   'import mlops_platform; print("runtime_version=" + mlops_platform.__version__)'

echo "M11 CI/CD + security + reliability smoke: PASSED"
echo "project_version=${PROJECT_VERSION}"
echo "trivy_gate=CRITICAL-fixed"
echo "release_signing=cosign-keyless"
