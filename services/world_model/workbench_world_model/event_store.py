import json
import sqlite3
from pathlib import Path

from workbench_contracts import WorldEvent


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
                "SELECT 1 FROM sqlite_master " "WHERE type = 'trigger' AND tbl_name = 'world_events' LIMIT 1"
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
            event.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def append(self, event: WorldEvent) -> None:
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

    def list_run(self, run_id: str) -> list[WorldEvent]:
        rows = self.connection.execute(
            "SELECT event_json FROM world_events WHERE run_id = ? ORDER BY sequence_no ASC", (run_id,)
        ).fetchall()
        return [WorldEvent.model_validate(json.loads(row[0])) for row in rows]

    def close(self) -> None:
        self.connection.close()
