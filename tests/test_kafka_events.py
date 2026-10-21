from pathlib import Path

import yaml

from mlops_platform.kafka_events import (
    KafkaPredictionPublisher,
    KafkaSettings,
    PredictionEvent,
)


class FakeProducer:
    def __init__(self) -> None:
        self.records = []
        self.poll_calls = 0
        self.flush_calls = 0

    def produce(self, topic, *, key, value, on_delivery):
        self.records.append((topic, key, value, on_delivery))

    def poll(self, timeout):
        assert timeout == 0
        self.poll_calls += 1

    def flush(self, timeout):
        assert timeout == 10.0
        self.flush_calls += 1
        return 0


def _settings() -> KafkaSettings:
    return KafkaSettings(
        enabled=True,
        bootstrap_servers="kafka:19092",
        prediction_topic="mlops.predictions.v1",
        consumer_group="mlops-monitoring-v1",
        topic_partitions=3,
        retained_batch_events=1000,
        delivery_timeout_ms=10000,
    )


def _event() -> PredictionEvent:
    return PredictionEvent.create(
        request_id="request-1",
        features={"feature_00": 1.5},
        prediction=1,
        probability=0.8,
        threshold=0.5,
        model_name="demo-model",
        model_alias="champion",
        model_version="2",
        run_id="run-1",
        dataset_sha256="a" * 64,
    )


def test_prediction_event_round_trips_as_versioned_json() -> None:
    event = _event()
    restored = PredictionEvent.model_validate_json(event.model_dump_json())

    assert restored.schema_version == "1.0"
    assert restored.event_type == "prediction"
    assert restored.request_id == event.request_id
    assert restored.features == {"feature_00": 1.5}


def test_kafka_publisher_queues_event_without_blocking_for_flush() -> None:
    fake = FakeProducer()
    publisher = KafkaPredictionPublisher(_settings(), producer=fake)

    status = publisher.publish(_event())
    publisher.close()

    assert status == "queued"
    assert fake.poll_calls == 1
    assert fake.flush_calls == 1
    assert fake.records[0][0] == "mlops.predictions.v1"
    assert fake.records[0][1] == b"request-1"


def test_kafka_settings_allow_environment_override(tmp_path: Path, monkeypatch) -> None:
    config = {"kafka": {"enabled": False, "bootstrap_servers": "localhost:29092"}}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setenv("MLOPS_KAFKA_ENABLED", "true")
    monkeypatch.setenv("MLOPS_KAFKA_BOOTSTRAP_SERVERS", "kafka:19092")

    settings = KafkaSettings.from_config(path)

    assert settings.enabled is True
    assert settings.bootstrap_servers == "kafka:19092"
