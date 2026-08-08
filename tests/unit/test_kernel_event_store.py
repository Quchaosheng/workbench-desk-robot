import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libs" / "kernel"))

from workbench.kernel.event_store import EventStore, EventStoreError


def test_checkpoint_counts_persisted_events_after_restart(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    first = EventStore(log)
    for event_id in range(3):
        first.append({"id": event_id})

    reopened = EventStore(log)
    reopened.append({"id": 3})
    checkpoint = reopened.create_checkpoint()

    assert checkpoint == 4
    assert reopened.replay(from_checkpoint=3) == [{"id": 3}]
    assert reopened.replay(from_checkpoint=checkpoint) == []


def test_replay_rejects_invalid_checkpoints(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.jsonl")
    store.append({"id": 0})

    for checkpoint in (-1, True, 2):
        with pytest.raises(ValueError, match="checkpoint must be between"):
            store.replay(from_checkpoint=checkpoint)


def test_corrupt_or_non_object_events_fail_integrity_check(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    store = EventStore(log)

    log.write_text('{"id": 0}\n{bad-json}\n', encoding="utf-8")
    assert not store.verify_integrity()
    with pytest.raises(EventStoreError, match="invalid event JSON"):
        store.create_checkpoint()

    log.write_text('{"id": 0}\n["not-an-object"]\n', encoding="utf-8")
    assert not store.verify_integrity()


def test_append_rejects_non_object_before_writing(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    store = EventStore(log)

    with pytest.raises(TypeError, match="event must be an object"):
        store.append(["not-an-object"])
    assert not log.exists()
