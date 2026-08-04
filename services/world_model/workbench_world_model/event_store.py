import json
import sqlite3
from pathlib import Path

from workbench_contracts import WorldEvent


class SQLiteEventStore:
    def __init__(self, database_path: str | Path) -> None:
        self.connection = sqlite3.connect(database_path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS world_events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                sequence_no INTEGER NOT NULL,
                event_json TEXT NOT NULL
            )
            """
        )

    def append(self, event: WorldEvent) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO world_events(event_id, run_id, sequence_no, event_json) VALUES (?, ?, ?, ?)",
            (event.event_id, event.run_id, event.sequence_no, event.model_dump_json()),
        )
        self.connection.commit()

    def list_run(self, run_id: str) -> list[WorldEvent]:
        rows = self.connection.execute(
            "SELECT event_json FROM world_events WHERE run_id = ? ORDER BY sequence_no", (run_id,)
        ).fetchall()
        return [WorldEvent.model_validate(json.loads(row[0])) for row in rows]

    def close(self) -> None:
        self.connection.close()
