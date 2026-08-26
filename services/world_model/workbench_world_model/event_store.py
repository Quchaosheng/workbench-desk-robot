import json
import sqlite3
from pathlib import Path
from typing import Any

from workbench_contracts import WorldEvent, WorldEventType

from .event_payloads import normalize_world_event


class EventStoreIntegrityError(RuntimeError):
    """The requested append conflicts with the persisted event stream."""


class EventStoreMigrationRequiredError(EventStoreIntegrityError):
    """The database schema cannot be upgraded safely by this store."""


class SQLiteEventStore:
    def __init__(self, database_path: str | Path) -> None:
        self.connection = sqlite3.connect(database_path)
        try:
            table_exists = self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'world_events'"
            ).fetchone()
            if table_exists is None:
                with self.connection:
                    self.connection.execute(
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
            self._validate_schema()
        except Exception:
            self.connection.close()
            raise

    def _validate_schema(self) -> None:
        columns = {row[1]: row for row in self.connection.execute("PRAGMA table_info(world_events)").fetchall()}
        expected_columns = {"event_id", "run_id", "sequence_no", "event_json"}
        has_world_event_triggers = (
            self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'world_events' LIMIT 1"
            ).fetchone()
            is not None
        )
        primary_key_columns = [row[1] for row in sorted(columns.values(), key=lambda column: column[5]) if row[5] > 0]
        event_id_is_only_primary_key = primary_key_columns == ["event_id"]
        required_columns_are_not_null = all(
            columns.get(name, (None,) * 4)[3] == 1 for name in ("run_id", "sequence_no", "event_json")
        )

        has_run_sequence_unique_index = False
        for index in self.connection.execute("PRAGMA index_list(world_events)").fetchall():
            if index[2] != 1 or index[4] != 0:
                continue
            indexed_columns = [
                row[0]
                for row in self.connection.execute(
                    "SELECT name FROM pragma_index_info(?) ORDER BY seqno", (index[1],)
                ).fetchall()
            ]
            if indexed_columns == ["run_id", "sequence_no"]:
                has_run_sequence_unique_index = True
                break

        if (
            set(columns) != expected_columns
            or not event_id_is_only_primary_key
            or not required_columns_are_not_null
            or not has_run_sequence_unique_index
            or has_world_event_triggers
        ):
            raise EventStoreMigrationRequiredError(
                "Unsupported legacy world_events schema. Create a backup, then rebuild the database "
                "with a fresh SQLiteEventStore and replay only validated events."
            )

    @staticmethod
    def _canonical_event_json(event: WorldEvent) -> str:
        return json.dumps(
            event.model_dump(mode="python"),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _parse_event_json(event_json: str) -> WorldEvent:
        return normalize_world_event(WorldEvent.model_validate_json(event_json))

    def append(self, event: WorldEvent) -> None:
        event = normalize_world_event(event)
        event_json = self._canonical_event_json(event)
        try:
            with self.connection:
                self.connection.execute(
                    "INSERT OR ABORT INTO world_events(event_id, run_id, sequence_no, event_json) VALUES (?, ?, ?, ?)",
                    (event.event_id, event.run_id, event.sequence_no, event_json),
                )
        except sqlite3.IntegrityError as error:
            existing_event = self.connection.execute(
                "SELECT run_id, sequence_no, event_json FROM world_events WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
            if existing_event is not None:
                if existing_event == (event.run_id, event.sequence_no, event_json):
                    return
                raise EventStoreIntegrityError(
                    f"event_id {event.event_id!r} already exists with different canonical event content"
                ) from error

            sequence_owner = self.connection.execute(
                "SELECT event_id FROM world_events WHERE run_id = ? AND sequence_no = ?",
                (event.run_id, event.sequence_no),
            ).fetchone()
            if sequence_owner is not None:
                raise EventStoreIntegrityError(
                    f"run_id {event.run_id!r} already contains sequence_no {event.sequence_no} "
                    f"for event_id {sequence_owner[0]!r}"
                ) from error
            raise EventStoreIntegrityError("world event violates an unknown SQLite integrity constraint") from error

    def _rollback_after_failure(self) -> None:
        try:
            self.connection.rollback()
        except sqlite3.Error:
            pass

    def append_allocated(
        self,
        *,
        event_id: str,
        run_id: str,
        event_type: WorldEventType,
        occurred_at: str,
        payload: dict[str, Any],
        evidence_refs: list[str] | None = None,
    ) -> WorldEvent:
        """Atomically allocate the next per-run sequence and append an event.

        Exact retries reuse the persisted sequence and event. Reusing an
        event_id with different canonical content fails closed.
        """
        references = list(evidence_refs or [])
        preflight = normalize_world_event(
            WorldEvent(
                event_id=event_id,
                run_id=run_id,
                sequence_no=0,
                event_type=event_type,
                occurred_at=occurred_at,
                payload=payload,
                evidence_refs=references,
            )
        )
        payload = preflight.payload
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            existing_row = self.connection.execute(
                "SELECT event_json FROM world_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if existing_row is not None:
                existing = self._parse_event_json(existing_row[0])
                candidate = WorldEvent(
                    event_id=event_id,
                    run_id=run_id,
                    sequence_no=existing.sequence_no,
                    event_type=event_type,
                    occurred_at=occurred_at,
                    payload=payload,
                    evidence_refs=references,
                )
                if self._canonical_event_json(candidate) != self._canonical_event_json(existing):
                    raise EventStoreIntegrityError(
                        f"event_id {event_id!r} already exists with different canonical event content"
                    )
                self.connection.commit()
                return existing

            maximum = self.connection.execute(
                "SELECT MAX(sequence_no) FROM world_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            sequence_no = (maximum[0] if maximum and maximum[0] is not None else 0) + 1
            event = WorldEvent(
                event_id=event_id,
                run_id=run_id,
                sequence_no=sequence_no,
                event_type=event_type,
                occurred_at=occurred_at,
                payload=payload,
                evidence_refs=references,
            )
            event_json = self._canonical_event_json(event)
            self.connection.execute(
                "INSERT OR ABORT INTO world_events(event_id, run_id, sequence_no, event_json) VALUES (?, ?, ?, ?)",
                (event.event_id, event.run_id, event.sequence_no, event_json),
            )
            self.connection.commit()
            return event
        except EventStoreIntegrityError:
            self._rollback_after_failure()
            raise
        except sqlite3.IntegrityError as error:
            self._rollback_after_failure()
            raise EventStoreIntegrityError("world event violates an unknown SQLite integrity constraint") from error
        except (sqlite3.Error, TypeError, ValueError):
            self._rollback_after_failure()
            raise

    def get_event(self, event_id: str) -> WorldEvent | None:
        row = self.connection.execute(
            "SELECT event_json FROM world_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        return None if row is None else self._parse_event_json(row[0])

    def list_run(self, run_id: str) -> list[WorldEvent]:
        rows = self.connection.execute(
            "SELECT event_json FROM world_events WHERE run_id = ? ORDER BY sequence_no ASC", (run_id,)
        ).fetchall()
        return [self._parse_event_json(row[0]) for row in rows]

    def close(self) -> None:
        self.connection.close()
