"""K6-K7: Event Store"""

import json
import threading
from pathlib import Path
from typing import Any


class EventStoreError(ValueError):
    """Raised when the persisted event log cannot be replayed safely."""


class EventStore:
    def __init__(self, log_file: Path):
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.events: list[dict[str, Any]] = []
        self.checkpoints: list[int] = []
        self._lock = threading.RLock()

    def _read_events(self) -> list[dict[str, Any]]:
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
        return events

    def append(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            raise TypeError("event must be an object")
        serialized = json.dumps(event, ensure_ascii=False)
        persisted_event = json.loads(serialized)
        with self._lock:
            events = self._read_events()
            try:
                with self.log_file.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(serialized + "\n")
            except OSError as exc:
                raise EventStoreError(f"event log could not be appended: {self.log_file}") from exc
            self.events = [*events, persisted_event]

    def create_checkpoint(self) -> int:
        with self._lock:
            self.events = self._read_events()
            checkpoint_id = len(self.events)
            self.checkpoints.append(checkpoint_id)
            return checkpoint_id

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
                self._read_events()
            except EventStoreError:
                return False
            return True
