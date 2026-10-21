#!/bin/sh
set -eu
CLUSTER_NAME="${KIND_CLUSTER_NAME:-mlops-platform}"
NAMESPACE="${K8S_NAMESPACE:-mlops-platform}"
CONTEXT="kind-${CLUSTER_NAME}"

kubectl --context "$CONTEXT" -n "$NAMESPACE" get pods,svc,deploy,statefulset,jobs,pvc -o wide
for app in mlflow api kafka-consumer prometheus grafana; do
    echo "===== $app ====="
    kubectl --context "$CONTEXT" -n "$NAMESPACE" logs         -l "app=$app" --tail=120 --all-containers=true || true
done
