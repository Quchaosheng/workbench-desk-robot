"""K6-K7: Event Store"""

import json
import threading
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


class EventStoreError(ValueError):
    """Raised when the persisted event log cannot be replayed safely."""


class EventStore:
    def __init__(self, log_file: Path, *, legacy_objects: bool = False):
        self.log_file = log_file
        self.legacy_objects = legacy_objects
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.events: list[dict[str, Any]] = []
        self.checkpoints: list[int] = []
        self._lock = threading.RLock()

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
        self._validate_events(events)
        return events

    def append(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            raise TypeError("event must be an object")
        try:
            serialized = json.dumps(event, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise EventStoreError("event must contain strict JSON values") from exc
        persisted_event = json.loads(serialized)
        with self._lock:
            events = self._read_events()
            self._validate_events([*events, persisted_event])
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
