"""Prediction event contract and Kafka publisher for the inference API."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from mlops_platform.data import load_config

LOGGER = logging.getLogger(__name__)
EVENT_SCHEMA_VERSION = "1.0"
EVENT_TYPE = "prediction"


class PredictionEvent(BaseModel):
    """Versioned event emitted for every successful online prediction."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=EVENT_SCHEMA_VERSION)
    event_type: str = Field(default=EVENT_TYPE)
    event_time: str
    request_id: str
    features: dict[str, float]
    prediction: int
    probability: float
    threshold: float
    model_name: str
    model_alias: str
    model_version: str
    run_id: str
    dataset_sha256: str

    @classmethod
    def create(
        cls,
        *,
        request_id: str,
        features: dict[str, float],
        prediction: int,
        probability: float,
        threshold: float,
        model_name: str,
        model_alias: str,
        model_version: str,
        run_id: str,
        dataset_sha256: str,
    ) -> PredictionEvent:
        return cls(
            event_time=datetime.now(UTC).isoformat(),
            request_id=request_id,
            features=features,
            prediction=prediction,
            probability=probability,
            threshold=threshold,
            model_name=model_name,
            model_alias=model_alias,
            model_version=model_version,
            run_id=run_id,
            dataset_sha256=dataset_sha256,
        )


@dataclass(frozen=True)
class KafkaSettings:
    enabled: bool
    bootstrap_servers: str
    prediction_topic: str
    consumer_group: str
    topic_partitions: int
    retained_batch_events: int
    delivery_timeout_ms: int

    @classmethod
    def from_config(cls, config_path: Path) -> KafkaSettings:
        config = load_config(config_path)
        values = config.get("kafka", {})
        configured_enabled = bool(values.get("enabled", False))
        enabled_raw = os.getenv("MLOPS_KAFKA_ENABLED")
        enabled = configured_enabled if enabled_raw is None else _parse_bool(enabled_raw)
        return cls(
            enabled=enabled,
            bootstrap_servers=os.getenv(
                "MLOPS_KAFKA_BOOTSTRAP_SERVERS",
                str(values.get("bootstrap_servers", "127.0.0.1:29092")),
            ),
            prediction_topic=os.getenv(
                "MLOPS_KAFKA_PREDICTION_TOPIC",
                str(values.get("prediction_topic", "mlops.predictions.v1")),
            ),
            consumer_group=os.getenv(
                "MLOPS_KAFKA_CONSUMER_GROUP",
                str(values.get("consumer_group", "mlops-monitoring-v1")),
            ),
            topic_partitions=int(
                os.getenv(
                    "MLOPS_KAFKA_TOPIC_PARTITIONS",
                    str(values.get("topic_partitions", 3)),
                )
            ),
            retained_batch_events=int(
                os.getenv(
                    "MLOPS_KAFKA_RETAINED_BATCH_EVENTS",
                    str(values.get("retained_batch_events", 1000)),
                )
            ),
            delivery_timeout_ms=int(
                os.getenv(
                    "MLOPS_KAFKA_DELIVERY_TIMEOUT_MS",
                    str(values.get("delivery_timeout_ms", 10000)),
                )
            ),
        )


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


class PredictionPublisher(Protocol):
    def publish(self, event: PredictionEvent) -> str: ...

    def close(self) -> None: ...


class DisabledPredictionPublisher:
    def publish(self, event: PredictionEvent) -> str:
        del event
        return "disabled"

    def close(self) -> None:
        return None


class KafkaPredictionPublisher:
    """Thin producer adapter with idempotence and fail-open API semantics."""

    def __init__(self, settings: KafkaSettings, producer: Any | None = None) -> None:
        self.settings = settings
        if producer is None:
            from confluent_kafka import Producer

            producer = Producer(
                {
                    "bootstrap.servers": settings.bootstrap_servers,
                    "client.id": "mlops-platform-api",
                    "enable.idempotence": True,
                    "acks": "all",
                    "compression.type": "gzip",
                    "linger.ms": 10,
                    "delivery.timeout.ms": settings.delivery_timeout_ms,
                }
            )
        self._producer = producer

    def publish(self, event: PredictionEvent) -> str:
        try:
            self._producer.produce(
                self.settings.prediction_topic,
                key=event.request_id.encode("utf-8"),
                value=event.model_dump_json().encode("utf-8"),
                on_delivery=self._delivery_callback,
            )
            self._producer.poll(0)
            return "queued"
        except Exception:
            LOGGER.exception("Failed to enqueue Kafka prediction event")
            return "error"

    def close(self) -> None:
        remaining = self._producer.flush(timeout=10.0)
        if remaining:
            LOGGER.error("Kafka producer shutdown left %s events undelivered", remaining)

    @staticmethod
    def _delivery_callback(error: Any, message: Any) -> None:
        if error is not None:
            LOGGER.error("Kafka delivery failed: %s", error)
            return
        LOGGER.debug(
            "Kafka event delivered topic=%s partition=%s offset=%s",
            message.topic(),
            message.partition(),
            message.offset(),
        )


def build_prediction_publisher(config_path: Path) -> PredictionPublisher:
    settings = KafkaSettings.from_config(config_path)
    if not settings.enabled:
        return DisabledPredictionPublisher()
    return KafkaPredictionPublisher(settings)
