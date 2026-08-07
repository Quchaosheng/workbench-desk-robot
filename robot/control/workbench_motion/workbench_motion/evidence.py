"""Execution-event structure and the EvidenceSink interface.

Design boundary (see robot/control/PLAN.md, phase 0):

- Motion does NOT own a fact store. This module defines *what* an execution
  event looks like and the *append-only* sink interface Motion talks to. It does
  not implement persistence, and it deliberately exposes no ``get``/query.
- Motion calls ``append(event)`` and receives back a **stable reference** it can
  drop into an ActionResult's ``evidence_refs``. Production persistence is
  provided by the World Model side (Event Store adapter) — see the "待确认"
  note in PLAN.md; that adapter is a cross-module dependency and is NOT assumed
  to exist yet.
- Unit tests use :class:`FakeEvidenceSink`.

Why events and not log lines: ``evidence_refs`` must point at something with a
stable id (an MCU frame number, or a structured event with a stable
``event_id``). Log lines are for humans and are not referenceable evidence.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# A stable, opaque reference returned by a sink after it durably records an
# event. Motion treats it as an opaque token and only stores it in evidence_refs.
EvidenceRef = str


@dataclass(frozen=True)
class ExecutionEvent:
    """An observed execution fact emitted by Motion.

    Frozen so an event cannot be mutated after it is handed to a sink. Carries
    ``run_id``/``action_id`` so it can be correlated with the (separate) human
    log stream, and a monotonic-clock-friendly ``clock_id`` per PLAN.md's
    timestamp discipline. This is intentionally minimal for phase 0; richer
    execution-fact fields land alongside the adapter in later phases.
    """

    event_type: str
    run_id: str
    action_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    clock_id: str = "monotonic"


@runtime_checkable
class EvidenceSink(Protocol):
    """Append-only sink Motion writes execution events to.

    The *only* operation Motion needs. Implementations must return a reference
    that is:
      - **stable**: identifies exactly the event that was appended, for later
        lookup by whoever owns the store.
      - **unique**: distinct per appended event, even for identical payloads.

    Motion holds no persistence itself and never reads back — there is no
    ``get`` here on purpose (no second event store).
    """

    def append(self, event: ExecutionEvent) -> EvidenceRef:
        """Durably record ``event`` and return a stable, unique reference."""
        ...


class FakeEvidenceSink:
    """In-memory test double implementing :class:`EvidenceSink`.

    For unit tests only. Keeps appended events so tests can assert on them, and
    mints a stable unique reference per append. This is NOT the production
    store — it exists so Motion tests never depend on the World Model adapter.
    """

    def __init__(self) -> None:
        self._events: list[tuple[EvidenceRef, ExecutionEvent]] = []

    def append(self, event: ExecutionEvent) -> EvidenceRef:
        ref: EvidenceRef = f"evt:{uuid.uuid4()}"
        self._events.append((ref, event))
        return ref

    # --- test-only inspection helpers (not part of the EvidenceSink interface) ---

    @property
    def events(self) -> list[ExecutionEvent]:
        """Events in append order."""
        return [event for _, event in self._events]

    @property
    def refs(self) -> list[EvidenceRef]:
        """References in append order."""
        return [ref for ref, _ in self._events]

    def __len__(self) -> int:
        return len(self._events)
