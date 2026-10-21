from pathlib import Path

import pandas as pd

from mlops_platform.kafka_consumer import (
    append_event,
    load_persisted_events,
    materialize_state,
)
from mlops_platform.kafka_events import PredictionEvent


def _event(request_id: str, value: float) -> PredictionEvent:
    return PredictionEvent.create(
        request_id=request_id,
        features={"feature_00": value, "feature_01": value + 1.0},
        prediction=int(value > 0),
        probability=0.8,
        threshold=0.5,
        model_name="demo-model",
        model_alias="champion",
        model_version="2",
        run_id="run-1",
        dataset_sha256="a" * 64,
    )


def test_persisted_log_recovers_bounded_monitoring_batch(tmp_path: Path) -> None:
    log_path = tmp_path / "events.jsonl"
    batch_path = tmp_path / "batch.csv"
    events = [_event(f"request-{index}", float(index)) for index in range(4)]
    for event in events:
        append_event(log_path, event)

    persisted = load_persisted_events(log_path)
    seen, recent = materialize_state(
        persisted,
        retained_batch_events=3,
        batch_path=batch_path,
    )

    batch = pd.read_csv(batch_path)
    assert seen == {event.request_id for event in events}
    assert [event.request_id for event in recent] == [
        "request-1",
        "request-2",
        "request-3",
    ]
    assert list(batch.columns) == ["row_id", "feature_00", "feature_01"]
    assert batch["feature_00"].tolist() == [1.0, 2.0, 3.0]
