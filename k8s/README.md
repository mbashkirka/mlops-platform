# M10 Kubernetes deployment

M10 keeps the earlier Docker Compose and Airflow workflows intact and adds a Kubernetes-native
online serving path for local development and portfolio demonstration.

The smoke environment uses kind with a digest-pinned Kubernetes v1.36.1 node image. It deploys
MLflow, a model-bootstrap Job, Kafka 4.3.1 in KRaft mode, a topic-initializer Job, a two-replica
FastAPI Deployment, a durable Kafka consumer, Prometheus, and Grafana.

The API uses startup/liveness/readiness probes, explicit requests and limits, a non-root security
context, a PodDisruptionBudget, and RollingUpdate with `maxUnavailable: 0` and `maxSurge: 1`.
Kafka keeps its broker non-root and uses a root-only init container to prepare its persistent KRaft
volume, preserving the storage-permission fix validated in M9.

Local endpoints after `make k8s-smoke`:

- API: http://127.0.0.1:8002
- MLflow: http://127.0.0.1:5052
- Prometheus: http://127.0.0.1:9093
- Grafana: http://127.0.0.1:3002

Use `make k8s-status` for cluster state, `make k8s-logs` for diagnostics, and `make k8s-delete`
to remove only the kind cluster.
