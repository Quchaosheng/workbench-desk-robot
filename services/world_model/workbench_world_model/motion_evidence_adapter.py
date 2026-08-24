"""Persist Motion action-result execution events in the World Model store.

The adapter is structurally compatible with Motion's append-only EvidenceSink,
but deliberately has no runtime import of the separately packaged
workbench_motion module.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import ValidationError
from workbench_contracts import ActionResult, WorldEvent, WorldEventType

from .event_store import SQLiteEventStore

REFERENCE_PREFIX = "world-event:"


class MotionEvidenceValidationError(ValueError):
    """The execution event cannot be represented as a valid ActionResult event."""


class SerializableExecutionEvent(Protocol):
    def as_serializable(self) -> dict[str, Any]:
        """Return the event as detached strict-JSON-ready data."""
        ...


class MotionEvidenceAdapter:
    """World Model-owned durable implementation of Motion's EvidenceSink."""

    def __init__(self, store: SQLiteEventStore) -> None:
        self._store = store

    def append(self, event: SerializableExecutionEvent) -> str:
        serialized = event.as_serializable()
        if not isinstance(serialized, dict):
            raise MotionEvidenceValidationError("ExecutionEvent.as_serializable() must return a mapping")

        json.dumps(
            serialized,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

        if serialized.get("event_type") != "action_result":
            raise MotionEvidenceValidationError("only action_result execution events can be persisted")

        try:
            result = ActionResult.model_validate(serialized.get("payload"))
        except ValidationError as error:
            raise MotionEvidenceValidationError("execution event payload is not a valid ActionResult") from error

        if serialized.get("run_id") != result.run_id:
            raise MotionEvidenceValidationError("ExecutionEvent run_id does not match ActionResult run_id")
        if serialized.get("action_id") != result.action_id:
            raise MotionEvidenceValidationError("ExecutionEvent action_id does not match ActionResult action_id")

        event_id = f"motion-result:{result.run_id}:{result.result_id}"
        stored = self._store.append_allocated(
            event_id=event_id,
            run_id=result.run_id,
            event_type=WorldEventType.ACTION_RESULT,
            occurred_at=result.ended_at,
            payload=result.model_dump(mode="json"),
            evidence_refs=list(result.evidence_refs),
        )
        return f"{REFERENCE_PREFIX}{stored.event_id}"

    def resolve(self, reference: str) -> WorldEvent | None:
        if not reference.startswith(REFERENCE_PREFIX):
            return None
        event_id = reference.removeprefix(REFERENCE_PREFIX)
        if not event_id:
            return None
        return self._store.get_event(event_id)
