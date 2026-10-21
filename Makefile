.PHONY: install lint format-check test quality portfolio-config portfolio-demo m12-smoke release-ready generate validate data train predict dvc-repro dvc-status mlflow-list mlflow-smoke mlflow-ui register registry-smoke registry-list api api-smoke docker-build compose-up compose-down compose-reset compose-config compose-ps compose-logs container-smoke compose-smoke airflow-config airflow-build airflow-up airflow-down airflow-reset airflow-ps airflow-logs airflow-dags airflow-smoke observability-config observability-up observability-down observability-reset observability-ps observability-logs observability-smoke monitor-batch-stable monitor-batch-drift monitor monitoring-reset monitoring-ps monitoring-logs monitoring-smoke clean kafka-config kafka-up kafka-down kafka-reset kafka-ps kafka-logs kafka-topics kafka-consumer-groups kafka-smoke k8s-prereqs k8s-config k8s-smoke k8s-status k8s-logs k8s-delete

CONFIG := configs/train.yaml
DATASET := data/raw/dataset.csv
ARTIFACT_DIR := artifacts
PROJECT_VERSION := 1.0.0
IMAGE := mlops-platform:$(PROJECT_VERSION)
MLFLOW_HOST_PORT ?= 5050
API_HOST_PORT ?= 8000
export MLFLOW_HOST_PORT API_HOST_PORT

AIRFLOW_VERSION ?= 3.3.1
AIRFLOW_IMAGE := mlops-platform-airflow:$(PROJECT_VERSION)
AIRFLOW_COMPOSE := docker compose -f compose.airflow.yaml
AIRFLOW_HOST_PORT ?= 8080
AIRFLOW_MLFLOW_HOST_PORT ?= 5051
AIRFLOW_API_HOST_PORT ?= 8001
export AIRFLOW_HOST_PORT AIRFLOW_MLFLOW_HOST_PORT AIRFLOW_API_HOST_PORT

OBS_COMPOSE := docker compose -f compose.airflow.yaml -f compose.observability.yaml
PROMETHEUS_HOST_PORT ?= 9091
GRAFANA_HOST_PORT ?= 3001
export PROMETHEUS_HOST_PORT GRAFANA_HOST_PORT

KAFKA_COMPOSE := docker compose -f compose.airflow.yaml -f compose.observability.yaml -f compose.kafka.yaml
KAFKA_HOST_PORT ?= 29092
export KAFKA_HOST_PORT

KIND_CLUSTER_NAME ?= mlops-platform
K8S_NAMESPACE ?= mlops-platform
KIND_NODE_IMAGE ?= kindest/node:v1.36.1@sha256:3489c7674813ba5d8b1a9977baea8a6e553784dab7b84759d1014dbd78f7ebd5
export KIND_CLUSTER_NAME K8S_NAMESPACE KIND_NODE_IMAGE

install:
	python -m pip install -e ".[dev]"

lint:
	python -m ruff check .

format-check:
	python -m ruff format --check .

test:
	python -m pytest

quality: lint format-check test

generate:
	python -m mlops_platform.data --config $(CONFIG) --output $(DATASET)

validate:
	python -m mlops_platform.data_validation --config $(CONFIG) --input $(DATASET) --report $(ARTIFACT_DIR)/data_validation.json --manifest $(ARTIFACT_DIR)/data_manifest.json

data: generate validate

train:
	python -m mlops_platform.train --config $(CONFIG) --data $(DATASET)

predict:
	python -m mlops_platform.predict --model $(ARTIFACT_DIR)/model.joblib --data $(DATASET) --sample-index 0

dvc-repro:
	python -m dvc repro

dvc-status:
	python -m dvc status

mlflow-list:
	python -m mlops_platform.experiments --config $(CONFIG) --limit 10

mlflow-smoke:
	python -m mlops_platform.mlflow_smoke --config $(CONFIG)

register:
	python -m mlops_platform.registry --config $(CONFIG)

registry-smoke:
	python -m mlops_platform.registry_smoke --config $(CONFIG)

registry-list:
	python -m mlops_platform.registry_list --config $(CONFIG)

api:
	python -m uvicorn mlops_platform.api:app --host 127.0.0.1 --port 8000

api-smoke:
	python -m mlops_platform.api_smoke --config $(CONFIG)

docker-build:
	docker build --tag $(IMAGE) .

compose-up:
	docker compose up --build -d

compose-down:
	docker compose down --remove-orphans

compose-config:
	docker compose config --quiet

compose-reset:
	docker compose down --volumes --remove-orphans

compose-ps:
	docker compose ps -a

compose-logs:
	docker compose logs --tail=200

container-smoke:
	python -m mlops_platform.container_smoke --base-url http://127.0.0.1:$(API_HOST_PORT) --wait-seconds 120

compose-smoke: compose-config compose-up container-smoke

airflow-config:
	$(AIRFLOW_COMPOSE) config --quiet

airflow-build:
	docker build -f Dockerfile.airflow --build-arg AIRFLOW_VERSION=$(AIRFLOW_VERSION) --tag $(AIRFLOW_IMAGE) .

airflow-up:
	$(AIRFLOW_COMPOSE) up --build -d airflow-apiserver airflow-scheduler airflow-dag-processor mlflow

airflow-down:
	$(AIRFLOW_COMPOSE) down --remove-orphans

airflow-reset:
	$(AIRFLOW_COMPOSE) down --volumes --remove-orphans

airflow-ps:
	$(AIRFLOW_COMPOSE) ps -a

airflow-logs:
	$(AIRFLOW_COMPOSE) logs --tail=300

airflow-dags:
	$(AIRFLOW_COMPOSE) exec -T airflow-scheduler airflow dags list

airflow-smoke: airflow-config
	sh scripts/airflow_smoke.sh

observability-config:
	$(OBS_COMPOSE) config --quiet

observability-up:
	$(OBS_COMPOSE) up --build -d

observability-down:
	$(OBS_COMPOSE) down --remove-orphans

observability-reset:
	$(OBS_COMPOSE) down --volumes --remove-orphans

observability-ps:
	$(OBS_COMPOSE) ps -a

observability-logs:
	$(OBS_COMPOSE) logs --tail=300

observability-smoke: observability-config
	sh scripts/observability_smoke.sh

monitor-batch-stable:
	python -m mlops_platform.monitoring_batch --config $(CONFIG) --source $(DATASET) --output data/monitoring/current_batch.csv --mode stable

monitor-batch-drift:
	python -m mlops_platform.monitoring_batch --config $(CONFIG) --source $(DATASET) --output data/monitoring/current_batch.csv --mode drifted --drift-features 8 --shift-sigma 3.0

monitor:
	python -m mlops_platform.monitoring --config $(CONFIG) --batch data/monitoring/current_batch.csv

monitoring-reset:
	$(OBS_COMPOSE) down --volumes --remove-orphans

monitoring-ps:
	$(OBS_COMPOSE) ps -a

monitoring-logs:
	$(OBS_COMPOSE) logs --tail=400

monitoring-smoke: observability-config
	sh scripts/monitoring_smoke.sh


kafka-config:
	$(KAFKA_COMPOSE) config --quiet

kafka-up:
	$(KAFKA_COMPOSE) up --build -d

kafka-down:
	$(KAFKA_COMPOSE) down --remove-orphans

kafka-reset:
	$(KAFKA_COMPOSE) down --volumes --remove-orphans

kafka-ps:
	$(KAFKA_COMPOSE) ps -a

kafka-logs:
	$(KAFKA_COMPOSE) logs --tail=500

kafka-topics:
	$(KAFKA_COMPOSE) exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:19092 --list

kafka-consumer-groups:
	$(KAFKA_COMPOSE) exec -T kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server kafka:19092 --describe --group mlops-monitoring-v1

kafka-smoke: kafka-config
	sh scripts/kafka_smoke.sh

mlflow-ui:
	python -m mlflow server --backend-store-uri sqlite:///mlflow.db --host 127.0.0.1 --port 5000

clean:
	rm -f $(DATASET) $(ARTIFACT_DIR)/data_validation.json $(ARTIFACT_DIR)/data_manifest.json $(ARTIFACT_DIR)/model.joblib $(ARTIFACT_DIR)/metrics.json $(ARTIFACT_DIR)/model_meta.json $(ARTIFACT_DIR)/mlflow_run.json $(ARTIFACT_DIR)/registry_decision.json $(ARTIFACT_DIR)/reference_profile.json $(ARTIFACT_DIR)/drift_report.json $(ARTIFACT_DIR)/retraining_decision.json dvc.lock mlflow.db
	rm -rf mlruns mlartifacts
	rm -f data/monitoring/*.csv


k8s-prereqs:
	@command -v docker >/dev/null || (echo "docker is required"; exit 2)
	@command -v kind >/dev/null || (echo "kind is required: brew install kind"; exit 2)
	@command -v kubectl >/dev/null || (echo "kubectl is required: brew install kubectl"; exit 2)


k8s-config:
	python scripts/k8s_validate.py


k8s-smoke: k8s-prereqs k8s-config
	sh scripts/k8s_smoke.sh


k8s-status:
	kubectl --context kind-$(KIND_CLUSTER_NAME) -n $(K8S_NAMESPACE) get pods,svc,deploy,statefulset,jobs,pvc -o wide


k8s-logs:
	sh scripts/k8s_logs.sh


k8s-delete:
	kind delete cluster --name $(KIND_CLUSTER_NAME)

security-config:
	python scripts/security_validate.py


release-config:
	python scripts/release_validate.py --tag v$(PROJECT_VERSION)


m11-prereqs:
	@command -v docker >/dev/null || (echo "docker is required"; exit 2)
	@command -v trivy >/dev/null || (echo "trivy is required: brew install trivy"; exit 2)


m11-smoke: m11-prereqs k8s-config security-config release-config
	PROJECT_VERSION=$(PROJECT_VERSION) sh scripts/m11_smoke.sh


portfolio-config:
	python scripts/portfolio_validate.py


portfolio-demo: k8s-prereqs portfolio-config
	PROJECT_VERSION=$(PROJECT_VERSION) sh scripts/portfolio_demo.sh


m12-smoke: quality k8s-config security-config release-config portfolio-config
	@echo "M12 final release readiness: PASSED"
	@echo "project_version=$(PROJECT_VERSION)"


release-ready: m12-smoke
