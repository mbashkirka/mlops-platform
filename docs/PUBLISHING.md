# Publishing Checklist

## Before making the repository public

1. Run the final gates:

```bash
make m12-smoke
make portfolio-demo
```

2. Review tracked files:

```bash
git status
git ls-files
```

Confirm that `.venv`, MLflow databases, DVC cache, generated artifacts, monitoring batches,
event logs, and credentials are not tracked.

3. Choose a software license deliberately. This snapshot does not select one automatically.

4. Review `SECURITY.md` and enable private vulnerability reporting on the hosting repository if
available.

5. Replace any repository-specific metadata only after the final GitHub repository name is known.

## Suggested repository metadata

Description:

```text
Production-oriented MLOps platform: DVC, MLflow, FastAPI, Airflow, Kafka,
Prometheus/Grafana, Kubernetes, drift monitoring, CI/CD, SBOM and Cosign.
```

Suggested topics:

```text
mlops
machine-learning
mlflow
fastapi
airflow
kafka
prometheus
grafana
kubernetes
docker
dvc
model-monitoring
github-actions
cosign
trivy
```

## Publish

After creating the remote repository:

```bash
git init
git add .
git commit -m "Release mlops-platform v1.0.0"
git branch -M main
git remote add origin <YOUR_GITHUB_REPOSITORY_URL>
git push -u origin main
```

Wait for the CI workflow to pass before creating the release tag.

```bash
git tag -a v1.0.0 -m "mlops-platform v1.0.0"
git push origin v1.0.0
```

The tag must match `pyproject.toml`. The release workflow then builds and scans the release
candidate, publishes the image to GHCR with SBOM/provenance, keyless-signs the immutable digest,
and verifies the signature.

## Recommended screenshots for the repository

Capture these from a successful `make portfolio-demo` run:

1. `kubectl get` output showing two API replicas and platform services.
2. MLflow registered model with the `champion` alias.
3. FastAPI `/docs`.
4. Grafana dashboard.
5. Prometheus query for API/Kafka metrics.
6. Kafka consumer group showing zero lag.
7. GitHub Actions CI and release workflow success.

Do not commit screenshots containing tokens, usernames, private paths, or unrelated desktop
content.

## Portfolio description

A concise CV/GitHub description can be:

> Built an end-to-end MLOps platform covering reproducible data/training, MLflow model
> governance, FastAPI serving, Airflow orchestration, Kafka event processing, drift-triggered
> retraining, Prometheus/Grafana observability, Kubernetes rolling deployment, and signed
> container releases with Trivy, SBOM, provenance, and Cosign.
