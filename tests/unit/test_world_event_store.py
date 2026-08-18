import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "libs/contracts"), str(ROOT / "services/world_model")]

from workbench_contracts import WorldEvent, WorldEventType
from workbench_world_model import event_store as event_store_module

SQLiteEventStore = event_store_module.SQLiteEventStore
EventStoreIntegrityError = event_store_module.EventStoreIntegrityError
EventStoreMigrationRequiredError = event_store_module.EventStoreMigrationRequiredError


def make_event(
    event_id: str,
    *,
    run_id: str = "run-001",
    sequence_no: int = 1,
    payload: dict[str, object] | None = None,
) -> WorldEvent:
    return WorldEvent(
        event_id=event_id,
        run_id=run_id,
        sequence_no=sequence_no,
        event_type=WorldEventType.OBSERVATION,
        occurred_at="2026-08-04T10:00:00Z",
        payload=payload or {"entity_id": "red_block", "location": "on:table"},
        evidence_refs=["camera-frame-001"],
    )


def open_legacy_store(database_path: Path, table_sql: str) -> SQLiteEventStore:
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(table_sql)
        connection.commit()
    finally:
        connection.close()
    return SQLiteEventStore(database_path)


def test_exact_reappend_is_idempotent(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite")
    event = make_event("evt-001")

    store.append(event)
    store.append(event)

    assert store.list_run("run-001") == [event]
    store.close()


def test_canonical_payload_key_order_is_idempotent(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite")
    first = make_event("evt-001", payload={"entity_id": "red_block", "confidence": 0.98})
    reordered = make_event("evt-001", payload={"confidence": 0.98, "entity_id": "red_block"})

    store.append(first)
    store.append(reordered)

    assert store.list_run("run-001") == [first]
    store.close()


def test_conflicting_event_id_raises_integrity_error_and_preserves_original(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite")
    original = make_event("evt-001")
    conflict = make_event("evt-001", payload={"entity_id": "blue_block", "location": "on:table"})
    store.append(original)

    with pytest.raises(EventStoreIntegrityError, match="event_id"):
        store.append(conflict)

    assert store.list_run("run-001") == [original]
    store.close()


def test_conflicting_run_sequence_raises_integrity_error_and_preserves_original(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite")
    original = make_event("evt-001")
    conflict = make_event("evt-002")
    store.append(original)

    with pytest.raises(EventStoreIntegrityError, match="run_id.*sequence_no"):
        store.append(conflict)

    assert store.list_run("run-001") == [original]
    store.close()


def test_same_sequence_number_is_allowed_for_different_runs(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite")
    first = make_event("evt-001", run_id="run-001")
    second = make_event("evt-002", run_id="run-002")

    store.append(first)
    store.append(second)

    assert store.list_run("run-001") == [first]
    assert store.list_run("run-002") == [second]
    store.close()


def test_failed_append_rolls_back_and_next_append_succeeds(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite")
    original = make_event("evt-001", sequence_no=1)
    conflict = make_event("evt-conflict", sequence_no=1)
    following = make_event("evt-002", sequence_no=2)
    store.append(original)

    with pytest.raises(EventStoreIntegrityError):
        store.append(conflict)
    store.append(following)

    assert store.list_run("run-001") == [original, following]
    store.close()


def test_list_run_orders_by_sequence_number(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite")
    events = [
        make_event("evt-003", sequence_no=3),
        make_event("evt-001", sequence_no=1),
        make_event("evt-002", sequence_no=2),
    ]
    for event in events:
        store.append(event)

    assert [event.sequence_no for event in store.list_run("run-001")] == [1, 2, 3]
    store.close()


def test_reopen_preserves_data_and_integrity_constraints(tmp_path: Path) -> None:
    database_path = tmp_path / "events.sqlite"
    original = make_event("evt-001")
    store = SQLiteEventStore(database_path)
    store.append(original)
    store.close()

    reopened = SQLiteEventStore(database_path)
    reopened.append(original)
    with pytest.raises(EventStoreIntegrityError, match="event_id"):
        reopened.append(
            make_event(
                "evt-001",
                payload={"entity_id": "blue_block", "location": "on:table"},
            )
        )
    with pytest.raises(EventStoreIntegrityError):
        reopened.append(make_event("evt-conflict"))

    assert reopened.list_run("run-001") == [original]
    reopened.close()


def test_legacy_table_fails_closed_with_recovery_instruction(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.sqlite"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE world_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            sequence_no INTEGER NOT NULL,
            event_json TEXT NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()

    try:
        store = SQLiteEventStore(database_path)
    except EventStoreMigrationRequiredError as exc:
        message = str(exc).lower()
        assert "backup" in message
        assert "rebuild" in message
    else:
        store.close()
        pytest.fail("legacy database must fail closed")

    connection = sqlite3.connect(database_path)
    columns = connection.execute("PRAGMA table_info(world_events)").fetchall()
    connection.close()
    assert [column[1] for column in columns] == ["event_id", "run_id", "sequence_no", "event_json"]


def test_legacy_partial_sequence_index_fails_closed(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-partial-index.sqlite"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE world_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            sequence_no INTEGER NOT NULL,
            event_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX unique_run_sequence_partial
        ON world_events(run_id, sequence_no)
        WHERE sequence_no > 100
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(EventStoreMigrationRequiredError, match="backup.*rebuild"):
        SQLiteEventStore(database_path)


def test_legacy_composite_event_primary_key_fails_closed(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-composite-primary-key.sqlite"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE world_events (
            event_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            sequence_no INTEGER NOT NULL,
            event_json TEXT NOT NULL,
            PRIMARY KEY(event_id, run_id),
            UNIQUE(run_id, sequence_no)
        )
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(EventStoreMigrationRequiredError, match="backup.*rebuild"):
        SQLiteEventStore(database_path)


def test_legacy_table_with_trigger_fails_closed(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-trigger.sqlite"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE world_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            sequence_no INTEGER NOT NULL,
            event_json TEXT NOT NULL,
            UNIQUE(run_id, sequence_no)
        )
        """
    )
    connection.execute(
        """
        CREATE TRIGGER ignore_world_event
        BEFORE INSERT ON world_events
        BEGIN
            SELECT RAISE(IGNORE);
        END
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(EventStoreMigrationRequiredError, match="backup.*rebuild"):
        SQLiteEventStore(database_path)


@pytest.mark.parametrize(
    "table_sql",
    [
        """
        CREATE TABLE world_events (
            event_id TEXT PRIMARY KEY ON CONFLICT IGNORE,
            run_id TEXT NOT NULL,
            sequence_no INTEGER NOT NULL,
            event_json TEXT NOT NULL,
            UNIQUE(run_id, sequence_no)
        )
        """,
        """
        CREATE TABLE world_events (
            event_id TEXT PRIMARY KEY ON CONFLICT REPLACE,
            run_id TEXT NOT NULL,
            sequence_no INTEGER NOT NULL,
            event_json TEXT NOT NULL,
            UNIQUE(run_id, sequence_no)
        )
        """,
    ],
    ids=["ignore", "replace"],
)
def test_event_id_conflict_policy_cannot_silence_typed_error(tmp_path: Path, table_sql: str) -> None:
    store = open_legacy_store(tmp_path / "legacy-event-id-policy.sqlite", table_sql)
    original = make_event("evt-001")
    conflict = make_event(
        "evt-001",
        sequence_no=2,
        payload={"entity_id": "blue_block", "location": "on:table"},
    )

    try:
        store.append(original)
        with pytest.raises(EventStoreIntegrityError, match="event_id"):
            store.append(conflict)
        assert store.list_run("run-001") == [original]
    finally:
        store.close()


@pytest.mark.parametrize(
    "table_sql",
    [
        """
        CREATE TABLE world_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            sequence_no INTEGER NOT NULL,
            event_json TEXT NOT NULL,
            UNIQUE(run_id, sequence_no) ON CONFLICT IGNORE
        )
        """,
        """
        CREATE TABLE world_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            sequence_no INTEGER NOT NULL,
            event_json TEXT NOT NULL,
            UNIQUE(run_id, sequence_no) ON CONFLICT REPLACE
        )
        """,
    ],
    ids=["ignore", "replace"],
)
def test_sequence_conflict_policy_cannot_silence_typed_error(tmp_path: Path, table_sql: str) -> None:
    store = open_legacy_store(tmp_path / "legacy-sequence-policy.sqlite", table_sql)
    original = make_event("evt-001")
    conflict = make_event(
        "evt-002",
        payload={"entity_id": "blue_block", "location": "on:table"},
    )

    try:
        store.append(original)
        with pytest.raises(EventStoreIntegrityError, match="run_id.*sequence_no"):
            store.append(conflict)
        assert store.list_run("run-001") == [original]
    finally:
        store.close()


def test_concurrent_sequence_conflict_has_one_winner(tmp_path: Path) -> None:
    database_path = tmp_path / "events.sqlite"
    initial = SQLiteEventStore(database_path)
    initial.close()
    barrier = Barrier(2)

    def append(event: WorldEvent) -> str:
        store = SQLiteEventStore(database_path)
        barrier.wait()
        try:
            store.append(event)
        except EventStoreIntegrityError:
            return "conflict"
        finally:
            store.close()
        return "stored"

    events = [make_event("evt-001"), make_event("evt-002")]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(append, events))

    store = SQLiteEventStore(database_path)
    stored = store.list_run("run-001")
    store.close()

    assert sorted(results) == ["conflict", "stored"]
    assert len(stored) == 1
    assert stored[0] in events
