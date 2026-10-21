"""Consume prediction events and materialize a monitoring batch."""

from __future__ import annotations

import argparse
import logging
import os
import signal
from collections import deque
from pathlib import Path
from typing import Any

import pandas as pd

from mlops_platform.kafka_events import KafkaSettings, PredictionEvent

LOGGER = logging.getLogger(__name__)


def load_persisted_events(path: Path) -> list[PredictionEvent]:
    if not path.exists():
        return []
    events: list[PredictionEvent] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line:
            events.append(PredictionEvent.model_validate_json(line))
    return events


def write_monitoring_batch(events: list[PredictionEvent], output_path: Path) -> None:
    rows: list[dict[str, float | int]] = []
    for row_id, event in enumerate(events):
        row: dict[str, float | int] = {"row_id": row_id}
        row.update(event.features)
        rows.append(row)

    if not rows:
        return
    frame = pd.DataFrame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(output_path)


def append_event(path: Path, event: PredictionEvent) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(event.model_dump_json())
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def materialize_state(
    persisted_events: list[PredictionEvent],
    *,
    retained_batch_events: int,
    batch_path: Path,
) -> tuple[set[str], deque[PredictionEvent]]:
    seen = {event.request_id for event in persisted_events}
    recent = deque(persisted_events[-retained_batch_events:], maxlen=retained_batch_events)
    write_monitoring_batch(list(recent), batch_path)
    return seen, recent


def run_consumer(
    *,
    config_path: Path,
    event_log_path: Path,
    batch_path: Path,
    ready_path: Path,
) -> None:
    from confluent_kafka import Consumer, KafkaException

    settings = KafkaSettings.from_config(config_path)
    persisted = load_persisted_events(event_log_path)
    seen, recent = materialize_state(
        persisted,
        retained_batch_events=settings.retained_batch_events,
        batch_path=batch_path,
    )

    consumer = Consumer(
        {
            "bootstrap.servers": settings.bootstrap_servers,
            "group.id": settings.consumer_group,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    running = True

    def stop(_signum: int, _frame: Any) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    consumer.subscribe([settings.prediction_topic])
    ready_path.parent.mkdir(parents=True, exist_ok=True)
    ready_path.write_text("ready\n", encoding="utf-8")

    try:
        while running:
            message = consumer.poll(1.0)
            if message is None:
                continue
            if message.error():
                raise KafkaException(message.error())

            event = PredictionEvent.model_validate_json(message.value())
            if event.request_id not in seen:
                append_event(event_log_path, event)
                seen.add(event.request_id)
                recent.append(event)
                write_monitoring_batch(list(recent), batch_path)
            consumer.commit(message=message, asynchronous=False)
    finally:
        ready_path.unlink(missing_ok=True)
        consumer.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/train.yaml"))
    parser.add_argument(
        "--event-log",
        type=Path,
        default=Path("/var/lib/mlops/events/prediction_events.jsonl"),
    )
    parser.add_argument(
        "--batch",
        type=Path,
        default=Path("data/monitoring/current_batch.csv"),
    )
    parser.add_argument(
        "--ready-file",
        type=Path,
        default=Path("/tmp/mlops-kafka-consumer.ready"),
    )
    args = parser.parse_args()
    run_consumer(
        config_path=args.config,
        event_log_path=args.event_log,
        batch_path=args.batch,
        ready_path=args.ready_file,
    )


if __name__ == "__main__":
    main()
