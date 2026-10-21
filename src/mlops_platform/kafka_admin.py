"""Create and validate Kafka topics required by the MLOps event layer."""

from __future__ import annotations

import argparse
from pathlib import Path

from mlops_platform.kafka_events import KafkaSettings


def ensure_prediction_topic(config_path: Path) -> None:
    from confluent_kafka.admin import AdminClient, NewTopic

    settings = KafkaSettings.from_config(config_path)
    admin = AdminClient({"bootstrap.servers": settings.bootstrap_servers})
    metadata = admin.list_topics(timeout=10)
    if settings.prediction_topic not in metadata.topics:
        futures = admin.create_topics(
            [
                NewTopic(
                    settings.prediction_topic,
                    num_partitions=settings.topic_partitions,
                    replication_factor=1,
                )
            ],
            request_timeout=10,
        )
        futures[settings.prediction_topic].result(timeout=15)

    metadata = admin.list_topics(topic=settings.prediction_topic, timeout=10)
    topic = metadata.topics[settings.prediction_topic]
    if topic.error is not None:
        raise RuntimeError(f"Kafka topic metadata error: {topic.error}")
    if len(topic.partitions) != settings.topic_partitions:
        raise RuntimeError(
            "Kafka topic partition mismatch: "
            f"expected {settings.topic_partitions}, got {len(topic.partitions)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/train.yaml"))
    args = parser.parse_args()
    ensure_prediction_topic(args.config)
    settings = KafkaSettings.from_config(args.config)
    print(f"kafka_topic={settings.prediction_topic}")
    print(f"partitions={settings.topic_partitions}")
    print("status=ready")


if __name__ == "__main__":
    main()
