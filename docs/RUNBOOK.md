# Operations Runbook

This runbook is for the local portfolio environment. It favors evidence-preserving diagnosis:
inspect the failed state before deleting containers, volumes, or the kind cluster.

## First checks

```bash
make quality
make k8s-config
make security-config
```

For Kubernetes:

```bash
make k8s-status
make k8s-logs
kubectl --context kind-mlops-platform -n mlops-platform get events   --sort-by=.lastTimestamp
```

For Docker Compose:

```bash
docker compose ps -a
docker compose logs --tail=300
```

## API is not ready

```bash
curl -i http://127.0.0.1:8002/health
curl -i http://127.0.0.1:8002/ready
kubectl --context kind-mlops-platform -n mlops-platform logs -l app=api --tail=200
```

`/health` proves the process is running. `/ready` additionally proves that the champion model
loaded successfully.

If readiness fails, inspect MLflow and the bootstrap Job before restarting the API.

## MLflow fails in Kubernetes

```bash
kubectl --context kind-mlops-platform -n mlops-platform describe pod -l app=mlflow
kubectl --context kind-mlops-platform -n mlops-platform logs -l app=mlflow --tail=300
kubectl --context kind-mlops-platform -n mlops-platform get pvc
```

The validated local configuration uses one MLflow worker, a 512 MiB memory request, and a 2 GiB
limit. `OOMKilled`/exit 137 means the memory limit was exceeded; do not misdiagnose the resulting
startup-probe failures as the root cause.

## Model bootstrap fails

```bash
kubectl --context kind-mlops-platform -n mlops-platform get pods -l job-name=model-bootstrap
kubectl --context kind-mlops-platform -n mlops-platform logs job/model-bootstrap --all-containers
```

Then verify that MLflow itself remained available:

```bash
kubectl --context kind-mlops-platform -n mlops-platform wait   --for=condition=Available deployment/mlflow --timeout=180s
```

## Kafka is unhealthy

```bash
kubectl --context kind-mlops-platform -n mlops-platform describe pod kafka-0
kubectl --context kind-mlops-platform -n mlops-platform logs kafka-0 --tail=300
```

The broker runs non-root. Its storage init container prepares ownership of the persistent KRaft
directory before the broker starts.

For the Compose version:

```bash
make kafka-ps
make kafka-logs
make kafka-topics
make kafka-consumer-groups
```

## Kafka consumer lag

```bash
kubectl --context kind-mlops-platform -n mlops-platform exec kafka-0   -- /opt/kafka/bin/kafka-consumer-groups.sh   --bootstrap-server kafka:19092   --describe   --group mlops-monitoring-v1
```

Check all partitions. Persistent lag indicates either a stopped/slow consumer or an event
processing failure. Inspect:

```bash
kubectl --context kind-mlops-platform -n mlops-platform logs -l app=kafka-consumer --tail=300
```

## Monitoring requests retraining

Inspect the decision artifacts:

```bash
cat artifacts/drift_report.json
cat artifacts/retraining_decision.json
```

`action=investigate` means the data-quality gate failed and automatic retraining is intentionally
disabled. `action=retrain` is only valid when quality passed and drift crossed policy thresholds.

## Docker Desktop image-store corruption

If Docker reports an internal containerd metadata I/O error before application containers start,
treat it as a Docker Desktop problem rather than a project failure. Preserve project files and
volumes first. A targeted image/cache refresh is preferable to factory reset.

Never use destructive Docker cleanup commands merely to hide an application-level failure.

## Security gate fails

```bash
make security-config
trivy image --ignore-unfixed --severity CRITICAL mlops-platform:1.0.0
```

Do not suppress a fixed critical vulnerability to make CI green. Update the affected dependency
or base image, rebuild, and rescan.

## Release tag rejected

```bash
python scripts/release_validate.py --tag v1.0.0
```

The Git tag must exactly match the version in `pyproject.toml`.

## Resetting local environments

Delete only the disposable kind cluster:

```bash
make k8s-delete
```

Stop Compose services without deleting named volumes:

```bash
make kafka-down
```

Use the `*-reset` targets only when a clean integration environment is explicitly required,
because those targets delete the corresponding Compose volumes.
