"""Append-only event storage with a strict JSONL compatibility path and SQLite backend."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EVENT_TYPES = {
    "observation",
    "action_request",
    "action_result",
    "verification",
    "fault",
    "emotion",
    "task_accepted",
    "task_terminal",
    "task_start",
    "tool_call",
    "policy_violation",
    "recovery_started",
    "recovery_complete",
}
REQUIRED_EVENT_FIELDS = {"event_id", "run_id", "sequence_no", "event_type", "occurred_at", "payload"}
SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
SCHEMA_VERSION = 1


class EventStoreError(ValueError):
    """Raised when persisted evidence cannot be written or replayed safely."""


class EventStore:
    """Persist one contiguous event run.

    SQLite is the default for database-looking paths (``.sqlite3``, ``.sqlite``
    and ``.db``). ``.jsonl`` remains an explicit compatibility format so old
    logs can be inspected and migrated without silently changing their meaning.
    """

    def __init__(self, log_file: Path, *, legacy_objects: bool = False, backend: str | None = None):
        self.log_file = Path(log_file)
        self.legacy_objects = legacy_objects
        self.backend = backend or ("sqlite" if self.log_file.suffix.lower() in SQLITE_SUFFIXES else "jsonl")
        if self.backend not in {"jsonl", "sqlite"}:
            raise ValueError("backend must be 'jsonl' or 'sqlite'")
        if self.backend == "sqlite" and legacy_objects:
            raise ValueError("legacy_objects is only supported by the JSONL compatibility backend")
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.events: list[dict[str, Any]] = []
        self.checkpoints: list[int] = []
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        self._events_signature: tuple[int, int, int] | None = None
        if self.backend == "sqlite":
            self._connection = sqlite3.connect(self.log_file)
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS event_store_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL UNIQUE,
                    event_json TEXT NOT NULL
                );
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO event_store_meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._connection.commit()
            self.checkpoints = [
                row[0]
                for row in self._connection.execute(
                    "SELECT event_count FROM checkpoints ORDER BY checkpoint_id"
                ).fetchall()
            ]

    def _jsonl_signature(self) -> tuple[int, int, int] | None:
        try:
            stat = self.log_file.stat()
        except FileNotFoundError:
            return None
        return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    def _validate_events(self, events: list[dict[str, Any]]) -> None:
        if self.legacy_objects:
            return
        expected_run_id: str | None = None
        event_ids: set[str] = set()
        for index, event in enumerate(events):
            missing = REQUIRED_EVENT_FIELDS - set(event)
            if missing:
                raise EventStoreError(f"event at index {index} is missing fields: {sorted(missing)}")
            event_id = event["event_id"]
            run_id = event["run_id"]
            sequence_no = event["sequence_no"]
            event_type = event["event_type"]
            occurred_at = event["occurred_at"]
            payload = event["payload"]
            evidence_refs = event.get("evidence_refs", [])
            if not isinstance(event_id, str) or not event_id:
                raise EventStoreError(f"event at index {index} has an invalid event_id")
            if event_id in event_ids:
                raise EventStoreError(f"event log has duplicate event_id {event_id!r}")
            event_ids.add(event_id)
            if not isinstance(run_id, str) or not run_id:
                raise EventStoreError(f"event at index {index} has an invalid run_id")
            if expected_run_id is None:
                expected_run_id = run_id
            elif run_id != expected_run_id:
                raise EventStoreError(f"event log mixes run_id {expected_run_id!r} and {run_id!r}")
            if type(sequence_no) is not int or sequence_no != index:
                raise EventStoreError(
                    f"event sequence_no must be contiguous from zero; index {index} has {sequence_no!r}"
                )
            if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
                raise EventStoreError(f"event at index {index} has an unknown event_type")
            if not isinstance(occurred_at, str) or not occurred_at:
                raise EventStoreError(f"event at index {index} has an invalid occurred_at")
            if not isinstance(payload, dict):
                raise EventStoreError(f"event at index {index} payload must be an object")
            if not isinstance(evidence_refs, list) or any(not isinstance(ref, str) for ref in evidence_refs):
                raise EventStoreError(f"event at index {index} evidence_refs must be a string list")

    def _read_jsonl(self) -> list[dict[str, Any]]:
        if not self.log_file.exists():
            return []
        events = []
        try:
            with self.log_file.open(encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise EventStoreError(f"invalid event JSON at line {line_number}") from exc
                    if not isinstance(event, dict):
                        raise EventStoreError(f"event at line {line_number} must be an object")
                    events.append(event)
        except (OSError, UnicodeError) as exc:
            raise EventStoreError(f"event log is unavailable or not UTF-8: {self.log_file}") from exc
        self._validate_events(events)
        return events

    def _read_sqlite(self) -> list[dict[str, Any]]:
        assert self._connection is not None
        try:
            version = self._connection.execute(
                "SELECT value FROM event_store_meta WHERE key = 'schema_version'"
            ).fetchone()
            if version != (str(SCHEMA_VERSION),):
                raise EventStoreError("event database schema version mismatch")
            rows = self._connection.execute(
                "SELECT event_id, run_id, sequence_no, event_json FROM events ORDER BY sequence_no"
            ).fetchall()
            events = []
            for index, (event_id, run_id, sequence_no, encoded) in enumerate(rows):
                try:
                    event = json.loads(encoded)
                except (TypeError, json.JSONDecodeError) as exc:
                    raise EventStoreError(f"invalid event JSON in SQLite row {index}") from exc
                if not isinstance(event, dict):
                    raise EventStoreError(f"event in SQLite row {index} must be an object")
                if (event.get("event_id"), event.get("run_id"), event.get("sequence_no")) != (
                    event_id,
                    run_id,
                    sequence_no,
                ):
                    raise EventStoreError(f"indexed fields disagree with SQLite row {index}")
                events.append(event)
            self._validate_events(events)
            return events
        except sqlite3.DatabaseError as exc:
            raise EventStoreError(f"event database is unavailable or corrupt: {self.log_file}") from exc

    def _read_events(self) -> list[dict[str, Any]]:
        return self._read_jsonl() if self.backend == "jsonl" else self._read_sqlite()

    def append(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            raise TypeError("event must be an object")
        self.append_many([event])

    def append_many(self, new_events: list[dict[str, Any]]) -> None:
        """Append a validated batch in one transaction."""
        if any(not isinstance(event, dict) for event in new_events):
            raise TypeError("event must be an object")
        try:
            serialized = [
                json.dumps(event, allow_nan=False, ensure_ascii=False, separators=(",", ":")) for event in new_events
            ]
        except (TypeError, ValueError) as exc:
            raise EventStoreError("event must contain strict JSON values") from exc
        persisted_events = [json.loads(encoded) for encoded in serialized]
        with self._lock:
            if self.backend == "jsonl" and self._events_signature == self._jsonl_signature():
                events = self.events
            else:
                events = self._read_events()
            self._validate_events([*events, *persisted_events])
            if self.backend == "jsonl":
                try:
                    with self.log_file.open("a", encoding="utf-8", newline="\n") as handle:
                        handle.writelines(f"{encoded}\n" for encoded in serialized)
                except OSError as exc:
                    raise EventStoreError(f"event log could not be appended: {self.log_file}") from exc
            else:
                assert self._connection is not None
                try:
                    self._connection.executemany(
                        "INSERT INTO events(event_id, run_id, sequence_no, event_json) VALUES (?, ?, ?, ?)",
                        [
                            (event["event_id"], event["run_id"], event["sequence_no"], encoded)
                            for event, encoded in zip(persisted_events, serialized, strict=True)
                        ],
                    )
                    self._connection.commit()
                except sqlite3.DatabaseError as exc:
                    self._connection.rollback()
                    raise EventStoreError(f"event database could not be appended: {self.log_file}") from exc
            self.events = [*events, *persisted_events]
            if self.backend == "jsonl":
                self._events_signature = self._jsonl_signature()

    def create_checkpoint(self) -> int:
        with self._lock:
            self.events = self._read_events()
            checkpoint = len(self.events)
            if self.backend == "sqlite":
                assert self._connection is not None
                try:
                    self._connection.execute("INSERT INTO checkpoints(event_count) VALUES (?)", (checkpoint,))
                    self._connection.commit()
                except sqlite3.DatabaseError as exc:
                    self._connection.rollback()
                    raise EventStoreError("checkpoint could not be persisted") from exc
                self.checkpoints = [
                    row[0]
                    for row in self._connection.execute(
                        "SELECT event_count FROM checkpoints ORDER BY checkpoint_id"
                    ).fetchall()
                ]
            else:
                self.checkpoints.append(checkpoint)
            return checkpoint

    def replay(self, from_checkpoint: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self.events = self._read_events()
            start_index = 0 if from_checkpoint is None else from_checkpoint
            if type(start_index) is not int or not 0 <= start_index <= len(self.events):
                raise ValueError(f"checkpoint must be between 0 and {len(self.events)}")
            return self.events[start_index:]

    def verify_integrity(self) -> bool:
        with self._lock:
            try:
                if self.backend == "sqlite":
                    assert self._connection is not None
                    result = self._connection.execute("PRAGMA integrity_check").fetchone()
                    if result != ("ok",):
                        return False
                self._read_events()
            except (EventStoreError, sqlite3.DatabaseError):
                return False
            return True

    def backup(self, destination: Path) -> Path:
        """Create a checksummed SQLite snapshot and return its manifest path."""
        if self.backend != "sqlite":
            raise EventStoreError("backup requires the SQLite backend")
        destination = Path(destination)
        if destination.resolve() == self.log_file.resolve():
            raise EventStoreError("snapshot destination must differ from the live database")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_name(f".{destination.name}.backup-tmp")
        if temp.exists():
            temp.unlink()
        with self._lock:
            assert self._connection is not None
            self._connection.commit()
            target = sqlite3.connect(temp)
            try:
                self._connection.backup(target)
            finally:
                target.close()
            self._read_events()
        manifest = {
            "format": "workbench-event-store-snapshot",
            "database": "sqlite",
            "sqlite_version": sqlite3.sqlite_version,
            "schema_version": SCHEMA_VERSION,
            "event_count": len(self.events),
            "created_at": datetime.now(UTC).isoformat(),
            "sha256": _sha256(temp),
        }
        manifest_path = Path(f"{destination}.manifest.json")
        manifest_temp = Path(f"{temp}.manifest.json")
        manifest_temp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, destination)
        os.replace(manifest_temp, manifest_path)
        return manifest_path

    @classmethod
    def restore(cls, snapshot: Path, destination: Path) -> EventStore:
        """Verify a snapshot before atomically replacing a destination database."""
        snapshot = Path(snapshot)
        destination = Path(destination)
        if snapshot.resolve() == destination.resolve():
            raise EventStoreError("restore destination must differ from the snapshot")
        manifest_path = Path(f"{snapshot}.manifest.json")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise EventStoreError("snapshot manifest is unavailable or malformed") from exc
        if (
            manifest.get("format") != "workbench-event-store-snapshot"
            or manifest.get("schema_version") != SCHEMA_VERSION
            or manifest.get("sha256") != _sha256(snapshot)
        ):
            raise EventStoreError("snapshot checksum or schema version mismatch")
        probe = cls(snapshot, backend="sqlite")
        try:
            if not probe.verify_integrity() or len(probe.replay()) != manifest.get("event_count"):
                raise EventStoreError("snapshot failed integrity or event-count verification")
        finally:
            probe.close()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_name(f".{destination.name}.restore-tmp")
        shutil.copy2(snapshot, temp)
        os.replace(temp, destination)
        shutil.copy2(manifest_path, Path(f"{destination}.manifest.json"))
        return cls(destination, backend="sqlite")

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> EventStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def migrate_jsonl(source: Path, destination: Path) -> EventStore:
    """Migrate a strict JSONL log into SQLite after validating every event."""
    source_store = EventStore(source, backend="jsonl")
    events = source_store.replay()
    destination = Path(destination)
    if destination.exists():
        raise EventStoreError(f"migration destination already exists: {destination}")
    temp = destination.with_name(f".{destination.name}.migration-tmp")
    if temp.exists():
        temp.unlink()
    target = EventStore(temp, backend="sqlite")
    try:
        target.append_many(events)
        target.close()
        os.replace(temp, destination)
    except Exception:
        target.close()
        raise
    return EventStore(destination, backend="sqlite")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
