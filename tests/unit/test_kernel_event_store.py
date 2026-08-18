import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libs" / "kernel"))

from workbench.kernel.event_store import EventStore, EventStoreError, migrate_jsonl


def event(event_id: int, *, run_id: str = "run-1", sequence_no: int | None = None) -> dict:
    return {
        "event_id": f"event-{event_id}",
        "run_id": run_id,
        "sequence_no": event_id if sequence_no is None else sequence_no,
        "event_type": "observation",
        "occurred_at": "2026-08-13T00:00:00Z",
        "payload": {"index": event_id},
        "evidence_refs": [],
    }


def test_checkpoint_counts_persisted_events_after_restart(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    first = EventStore(log)
    for event_id in range(3):
        first.append(event(event_id))

    reopened = EventStore(log)
    reopened.append(event(3))
    checkpoint = reopened.create_checkpoint()

    assert checkpoint == 4
    assert reopened.replay(from_checkpoint=3) == [event(3)]
    assert reopened.replay(from_checkpoint=checkpoint) == []


def test_replay_rejects_invalid_checkpoints(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.jsonl")
    store.append(event(0))

    for checkpoint in (-1, True, 2):
        with pytest.raises(ValueError, match="checkpoint must be between"):
            store.replay(from_checkpoint=checkpoint)


def test_corrupt_or_non_object_events_fail_integrity_check(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    store = EventStore(log)

    log.write_text(f"{json.dumps(event(0))}\n{{bad-json}}\n", encoding="utf-8")
    assert not store.verify_integrity()
    with pytest.raises(EventStoreError, match="invalid event JSON"):
        store.create_checkpoint()

    log.write_text(f'{json.dumps(event(0))}\n["not-an-object"]\n', encoding="utf-8")
    assert not store.verify_integrity()


def test_append_rejects_non_object_before_writing(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    store = EventStore(log)

    with pytest.raises(TypeError, match="event must be an object"):
        store.append(["not-an-object"])
    assert not log.exists()


@pytest.mark.parametrize(
    "bad_event, message",
    [
        ({"garbage": True}, "missing fields"),
        (event(0, sequence_no=1), "contiguous"),
        ({**event(0), "event_type": "unknown"}, "unknown event_type"),
        ({**event(0), "payload": []}, "payload must be an object"),
        ({**event(0), "evidence_refs": [1]}, "string list"),
    ],
)
def test_append_rejects_invalid_event_contract(tmp_path: Path, bad_event: dict, message: str) -> None:
    log = tmp_path / "events.jsonl"
    store = EventStore(log)
    with pytest.raises(EventStoreError, match=message):
        store.append(bad_event)
    assert not log.exists()


def test_append_rejects_duplicate_identity_and_mixed_run_before_writing(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    store = EventStore(log)
    store.append(event(0))
    before = log.read_bytes()

    with pytest.raises(EventStoreError, match="duplicate event_id"):
        store.append({**event(1), "event_id": "event-0"})
    assert log.read_bytes() == before

    with pytest.raises(EventStoreError, match="mixes run_id"):
        store.append(event(1, run_id="run-2"))
    assert log.read_bytes() == before


def test_integrity_checks_contract_and_strict_json(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    store = EventStore(log)
    log.write_text('{"garbage":true}\n', encoding="utf-8")
    assert not store.verify_integrity()
    with pytest.raises(EventStoreError, match="missing fields"):
        store.replay()

    with pytest.raises(EventStoreError, match="strict JSON"):
        EventStore(tmp_path / "nan.jsonl").append({**event(0), "payload": {"confidence": float("nan")}})


def test_legacy_object_mode_is_explicit(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "legacy.jsonl", legacy_objects=True)
    store.append({"id": 0})
    assert store.verify_integrity()
    assert store.replay() == [{"id": 0}]


def test_sqlite_restart_checkpoint_and_unknown_fields(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    first = EventStore(database)
    first.append({**event(0), "extension": {"source": "bench"}})
    first.append(event(1))
    checkpoint = first.create_checkpoint()
    first.close()

    reopened = EventStore(database)
    assert reopened.checkpoints == [2]
    assert reopened.replay(from_checkpoint=checkpoint) == []
    assert reopened.replay()[0]["extension"] == {"source": "bench"}
    assert reopened.verify_integrity()
    reopened.close()


def test_jsonl_migration_and_verified_restore(tmp_path: Path) -> None:
    source = tmp_path / "events.jsonl"
    legacy = EventStore(source)
    legacy.append(event(0))
    legacy.append(event(1))
    database = tmp_path / "events.sqlite3"
    migrated = migrate_jsonl(source, database)
    assert migrated.replay() == [event(0), event(1)]
    snapshot = tmp_path / "events.snapshot.sqlite3"
    manifest = migrated.backup(snapshot)
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    migrated.close()
    restored = EventStore.restore(snapshot, tmp_path / "restored.sqlite3")
    assert manifest.exists()
    assert metadata["database"] == "sqlite"
    assert metadata["sqlite_version"]
    assert metadata["created_at"].endswith("+00:00")
    assert restored.replay() == [event(0), event(1)]
    restored.close()

    snapshot.write_bytes(snapshot.read_bytes() + b"tamper")
    with pytest.raises(EventStoreError, match="checksum"):
        EventStore.restore(snapshot, tmp_path / "rejected.sqlite3")


def test_sqlite_batch_is_atomic_on_contract_failure(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.sqlite3")
    with pytest.raises(EventStoreError, match="contiguous"):
        store.append_many([event(0), event(2)])
    assert store.replay() == []
    store.close()
