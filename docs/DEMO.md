# Portfolio Demo

## One-command full demo

Prerequisites:

```bash
brew install kind kubectl trivy
```

From the project virtual environment:

```bash
make portfolio-demo
```

The command creates a clean kind cluster and exercises the same path validated by M10:

1. build and load the application image;
2. start MLflow and verify it remains healthy during model bootstrap;
3. start Kafka and initialize the prediction topic;
4. start two FastAPI replicas and the durable Kafka consumer;
5. execute a real prediction against the champion model;
6. generate Kafka-backed inference traffic;
7. confirm durable event persistence and zero consumer lag;
8. verify Prometheus and Grafana;
9. execute a zero-unavailable API rolling update.

The cluster is intentionally left running so the interfaces can be shown after the smoke test.

## What to show in an interview

### 1. Model identity

```bash
curl -s http://127.0.0.1:8002/v1/model-info
```

Explain that serving resolves the MLflow `champion` alias and returns model version, source run,
dataset fingerprint, feature count, threshold, and project version.

### 2. Kubernetes state

```bash
make k8s-status
```

Point out:

- two API replicas;
- MLflow;
- Kafka StatefulSet;
- durable consumer;
- Prometheus and Grafana;
- completed bootstrap/topic Jobs;
- bound PVCs.

### 3. Event pipeline

```bash
kubectl --context kind-mlops-platform -n mlops-platform exec kafka-0   -- /opt/kafka/bin/kafka-consumer-groups.sh   --bootstrap-server kafka:19092   --describe   --group mlops-monitoring-v1
```

The important signal is `LAG=0` for every partition after the demo traffic has been consumed.

### 4. Observability

Open:

- FastAPI docs: `http://127.0.0.1:8002/docs`
- MLflow: `http://127.0.0.1:5052`
- Prometheus: `http://127.0.0.1:9093`
- Grafana: `http://127.0.0.1:3002`

In Prometheus, query:

```text
mlops_model_ready
```

and:

```text
sum by (status) (rate(mlops_kafka_publish_total[1m]))
```

### 5. Reliability and security

Show:

```bash
make security-config
make release-config
```

Explain:

- non-root runtime;
- capability dropping and seccomp;
- service-account token disabled for first-party workloads;
- Trivy release gate;
- SBOM and provenance;
- keyless Cosign signing;
- two-replica rolling update with `maxUnavailable: 0`.

## Short interview narrative

> I kept the model deliberately simple and concentrated complexity in the lifecycle around it:
> reproducible data, lineage, registry governance, online serving, event streaming, monitoring,
> automated retraining decisions, orchestration, observability, Kubernetes deployment, and a
> signed software-supply-chain release.

## Cleanup

```bash
make k8s-delete
```
