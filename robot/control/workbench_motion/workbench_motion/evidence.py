"""Execution-event structure and the EvidenceSink interface.

Design boundary:

- Motion does NOT own a fact store. This module defines *what* an execution
  event looks like and the *append-only* sink interface Motion talks to. It does
  not implement persistence, and it deliberately exposes no ``get``/query.
- Motion calls ``append(event)`` and receives back a **stable reference** it can
  drop into an ActionResult's ``evidence_refs``. Production persistence is
  provided by the World Model side (Event Store adapter); that adapter is a
  cross-module dependency and is NOT assumed to exist yet.
- Unit tests use :class:`FakeEvidenceSink`.

Why events and not log lines: ``evidence_refs`` must point at something with a
stable id (an MCU frame number, or a structured event with a stable
``event_id``). Log lines are for humans and are not referenceable evidence.
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

# A stable, opaque reference returned by a sink after it durably records an
# event. Motion treats it as an opaque token and only stores it in evidence_refs.
EvidenceRef = str


def _freeze(value: Any, *, _ancestors: set[int] | None = None) -> Any:
    """Recursively rebuild ``value`` into a deeply-immutable structure.

    - ``dict``/``Mapping`` -> ``MappingProxyType`` of frozen items.
    - ``list``/``tuple`` (non-str Sequence) -> ``tuple`` of frozen items.
    - ``set``/``frozenset`` -> ``frozenset`` of frozen items.
    - strict-JSON scalar values are returned as-is; NaN/Infinity are rejected.
    - unsupported values, non-string mapping keys, and cycles fail closed.

    Because containers are rebuilt from scratch, the result shares no mutable
    object with the caller's input — passing an existing dict OR MappingProxyType
    and then mutating the original cannot reach the frozen copy. This is what
    ``frozen=True`` alone does NOT give you (it only blocks field reassignment,
    not mutation of a dict the field points at).
    """
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("payload float values must be finite")
        return value
    if value is None or isinstance(value, str | int | bool):
        return value

    ancestors = set() if _ancestors is None else _ancestors
    identity = id(value)
    if identity in ancestors:
        raise TypeError("payload must not contain recursive containers")

    if isinstance(value, Mapping):
        ancestors.add(identity)
        try:
            frozen: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError("payload mapping keys must be strings")
                frozen[key] = _freeze(item, _ancestors=ancestors)
            return MappingProxyType(frozen)
        finally:
            ancestors.remove(identity)

    if isinstance(value, Set):
        ancestors.add(identity)
        try:
            return frozenset(_freeze(item, _ancestors=ancestors) for item in value)
        finally:
            ancestors.remove(identity)

    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        ancestors.add(identity)
        try:
            return tuple(_freeze(item, _ancestors=ancestors) for item in value)
        finally:
            ancestors.remove(identity)

    raise TypeError(f"unsupported payload value type: {type(value).__name__}")


def _json_sort_key(value: Any) -> str:
    """Return a stable key for values thawed from an unordered set."""
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _thaw(value: Any) -> Any:
    """Inverse of :func:`_freeze`: rebuild plain ``dict``/``list`` for serialization.

    ``MappingProxyType`` is not JSON-serializable and breaks ``json.dumps`` /
    ``dataclasses.asdict``. Consumers that need to persist an event call
    :meth:`ExecutionEvent.as_serializable` (which routes through this) to get a
    plain, JSON-ready structure back. Frozen sets become deterministically
    ordered lists so repeated serialization produces stable evidence bytes.
    """
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return sorted((_thaw(item) for item in value), key=_json_sort_key)
    return value


@dataclass(frozen=True)
class ExecutionEvent:
    """An observed execution fact emitted by Motion.

    An archived event must be tamper-proof. ``frozen=True`` alone is not enough:
    it blocks field reassignment but not mutation of a ``dict``/``list`` a field
    points at. So ``__post_init__`` recursively rebuilds ``payload`` into a
    deeply-immutable structure (``MappingProxyType``/``tuple``, see :func:`_freeze`)
    that shares no mutable object with the caller — nested values cannot be
    changed, and the input reference (dict OR MappingProxyType) cannot reach the
    stored copy afterwards.

    Because that structure is not JSON-serializable, :meth:`as_serializable`
    thaws it back to plain ``dict``/``list`` for a persisting EvidenceSink.

    Carries ``run_id``/``action_id`` so it can be correlated with the (separate)
    human log stream, and a monotonic-clock-friendly ``clock_id`` for consistent
    timestamps. Intentionally minimal for phase 0; richer fields land alongside
    the adapter in later phases.
    """

    event_type: str
    run_id: str
    action_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    clock_id: str = "monotonic"

    def __post_init__(self) -> None:
        # Deep-freeze payload. frozen=True blocks reassignment, so set via
        # object.__setattr__. _freeze rebuilds every container, so this is safe
        # (and correct) whether payload came in as a dict or a MappingProxyType.
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping")
        object.__setattr__(self, "payload", _freeze(self.payload))

    def as_serializable(self) -> dict[str, Any]:
        """Return a plain, strict-JSON-ready dict of this event (payload thawed).

        Use this for persistence/serialization — ``json.dumps`` and
        ``dataclasses.asdict`` cannot handle the frozen ``MappingProxyType``
        payload directly.
        """
        return {
            "event_type": self.event_type,
            "run_id": self.run_id,
            "action_id": self.action_id,
            "payload": _thaw(self.payload),
            "clock_id": self.clock_id,
        }


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

    ``ExecutionEvent`` deliberately stores a deeply immutable payload and is
    therefore not directly JSON-serializable. A persisting implementation MUST
    serialize :meth:`ExecutionEvent.as_serializable`; it must not use
    ``json.dumps(event)`` or ``dataclasses.asdict(event)``.

    Validation, serialization, or durable-write failures MUST be raised to the
    caller. An implementation must not swallow a failure or mint an evidence
    reference for an event that was not durably recorded.
    """

    def append(self, event: ExecutionEvent) -> EvidenceRef:
        """Durably record ``event.as_serializable()`` and return its reference."""
        ...


class FakeEvidenceSink:
    """In-memory test double implementing :class:`EvidenceSink`.

    For unit tests only. Keeps appended events so tests can assert on them, and
    mints a stable unique reference per append. This is NOT the production
    store — it exists so Motion tests never depend on the World Model adapter.
    ``append_error`` provides deterministic failure injection for caller tests.
    """

    def __init__(self, *, append_error: Exception | None = None) -> None:
        self._events: list[tuple[EvidenceRef, ExecutionEvent]] = []
        self._append_error = append_error

    def append(self, event: ExecutionEvent) -> EvidenceRef:
        if self._append_error is not None:
            raise self._append_error
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
