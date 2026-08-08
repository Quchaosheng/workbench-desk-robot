"""Unit tests for the EvidenceSink interface and FakeEvidenceSink.

Proves the phase-0 acceptance criterion: ``append()`` returns a stable, unique
reference, and Motion holds no persistence implementation (no ``get`` on the
interface).
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest
from workbench_motion.evidence import EvidenceSink, ExecutionEvent, FakeEvidenceSink


def _event(action_id: str = "a-1") -> ExecutionEvent:
    return ExecutionEvent(
        event_type="trajectory_completed",
        run_id="run-1",
        action_id=action_id,
        payload={"controller": "succeeded"},
    )


def test_fake_sink_satisfies_interface() -> None:
    sink = FakeEvidenceSink()
    # runtime_checkable Protocol: the fake structurally implements EvidenceSink.
    assert isinstance(sink, EvidenceSink)


def test_append_returns_reference() -> None:
    sink = FakeEvidenceSink()
    ref = sink.append(_event())
    assert isinstance(ref, str)
    assert ref


def test_reference_is_unique_even_for_identical_events() -> None:
    sink = FakeEvidenceSink()
    ref_a = sink.append(_event())
    ref_b = sink.append(_event())  # identical payload/ids
    assert ref_a != ref_b
    assert len(set(sink.refs)) == len(sink.refs) == 2


def test_reference_is_stable_and_maps_to_its_event() -> None:
    sink = FakeEvidenceSink()
    ref_first = sink.append(_event("a-1"))
    ref_second = sink.append(_event("a-2"))
    # The reference returned for an append does not change and keeps pointing at
    # the same event position it was minted for.
    assert sink.refs == [ref_first, ref_second]
    assert sink.events[0].action_id == "a-1"
    assert sink.events[1].action_id == "a-2"


def test_events_are_immutable() -> None:
    sink = FakeEvidenceSink()
    sink.append(_event())
    archived = sink.events[0]

    with pytest.raises(FrozenInstanceError):
        archived.action_id = "mutated"  # type: ignore[misc]


def test_payload_is_deeply_immutable_from_dict_input() -> None:
    """Archived events cannot be tampered with, at ANY nesting depth.

    Covers the review concern that the earlier fix was only shallow: mutating the
    original dict (top-level or nested), or writing through ``event.payload`` at
    top level or into a nested dict/list, must all fail to reach the archive.
    """
    original = {"status": "ok", "nested": {"count": 1}, "items": [1, 2]}
    event = ExecutionEvent(event_type="t", run_id="r", action_id="a", payload=original)
    sink = FakeEvidenceSink()
    sink.append(event)
    archived = sink.events[0]

    # 1. Mutating the ORIGINAL input (any depth) must not reach the archive.
    original["status"] = "corrupted"
    original["nested"]["count"] = 999
    original["items"].append(3)
    assert archived.payload["status"] == "ok"
    assert archived.payload["nested"]["count"] == 1
    assert archived.payload["items"] == (1, 2)

    # 2. Writing through event.payload at top level must raise.
    with pytest.raises(TypeError):
        archived.payload["status"] = "x"  # type: ignore[index]

    # 3. Writing into a NESTED dict must also raise (this is what shallow failed).
    with pytest.raises(TypeError):
        archived.payload["nested"]["count"] = 0  # type: ignore[index]

    # 4. Nested sequences become tuples — no append/mutation possible.
    assert isinstance(archived.payload["items"], tuple)
    with pytest.raises(AttributeError):
        archived.payload["items"].append(4)  # type: ignore[attr-defined]


def test_payload_is_isolated_from_mappingproxy_input() -> None:
    """Passing an existing MappingProxyType must NOT leak its backing dict.

    Covers the review concern: the earlier fix skipped copying when the input was
    already a MappingProxyType, so a caller holding the backing dict could still
    mutate the archived event. _freeze rebuilds regardless, closing that hole.
    """
    from types import MappingProxyType

    backing = {"k": {"n": 1}}
    proxy = MappingProxyType(backing)
    event = ExecutionEvent(event_type="t", run_id="r", action_id="a", payload=proxy)
    sink = FakeEvidenceSink()
    sink.append(event)
    archived = sink.events[0]

    # Mutate the underlying dict the proxy was built from.
    backing["k"]["n"] = 999
    backing["added"] = True

    assert archived.payload["k"]["n"] == 1
    assert "added" not in archived.payload


def test_as_serializable_returns_plain_json_ready_dict() -> None:
    """The frozen payload is not JSON-serializable; as_serializable() thaws it.

    Covers the serialization-regression concern: json.dumps must work on the
    output, and nested structures come back as plain dict/list.
    """
    event = ExecutionEvent(
        event_type="grasp_done",
        run_id="run-1",
        action_id="a-1",
        payload={"controller": "succeeded", "joints": [0.1, 0.2], "meta": {"ok": True}},
    )
    data = event.as_serializable()

    # Plain types, round-trips through JSON without error.
    assert isinstance(data["payload"], dict)
    assert isinstance(data["payload"]["joints"], list)
    assert isinstance(data["payload"]["meta"], dict)
    restored = json.loads(json.dumps(data, allow_nan=False))
    assert restored["payload"]["controller"] == "succeeded"
    assert restored["payload"]["joints"] == [0.1, 0.2]
    assert restored["event_type"] == "grasp_done"


def test_set_payload_is_deeply_immutable_and_json_ready() -> None:
    original = {3, 1, 2}
    event = ExecutionEvent(
        event_type="controller_failed",
        run_id="run-1",
        action_id="a-1",
        payload={"fault_codes": original, "nested": {"labels": frozenset({"b", "a"})}},
    )
    sink = FakeEvidenceSink()
    sink.append(event)
    archived = sink.events[0]

    original.add(4)
    assert archived.payload["fault_codes"] == frozenset({1, 2, 3})
    assert archived.payload["nested"]["labels"] == frozenset({"a", "b"})
    with pytest.raises(AttributeError):
        archived.payload["fault_codes"].add(5)  # type: ignore[attr-defined]

    serialized = archived.as_serializable()
    assert serialized["payload"]["fault_codes"] == [1, 2, 3]
    assert serialized["payload"]["nested"]["labels"] == ["a", "b"]
    assert json.loads(json.dumps(serialized)) == serialized


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_float_payloads_fail_closed(value: float) -> None:
    with pytest.raises(ValueError, match="float values must be finite"):
        ExecutionEvent(
            event_type="controller_failed",
            run_id="run-1",
            action_id="a-1",
            payload={"position_error": value},
        )


def test_invalid_payload_types_fail_closed() -> None:
    class MutableValue:
        pass

    with pytest.raises(TypeError, match="payload must be a mapping"):
        ExecutionEvent(event_type="t", run_id="r", action_id="a", payload=[])  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="mapping keys must be strings"):
        ExecutionEvent(event_type="t", run_id="r", action_id="a", payload={1: "bad"})  # type: ignore[dict-item]

    with pytest.raises(TypeError, match="unsupported payload value type: MutableValue"):
        ExecutionEvent(
            event_type="t",
            run_id="r",
            action_id="a",
            payload={"bad": MutableValue()},
        )


def test_recursive_payload_fails_closed() -> None:
    recursive: dict[str, object] = {}
    recursive["self"] = recursive

    with pytest.raises(TypeError, match="must not contain recursive containers"):
        ExecutionEvent(event_type="t", run_id="r", action_id="a", payload=recursive)


def test_sink_append_error_propagates_without_minting_reference() -> None:
    sink = FakeEvidenceSink(append_error=RuntimeError("durable append failed"))

    with pytest.raises(RuntimeError, match="durable append failed"):
        sink.append(_event())

    assert len(sink) == 0
    assert sink.refs == []


def test_motion_side_holds_no_read_api() -> None:
    # Enforce the boundary: the interface Motion talks to exposes append only,
    # never a get/query. Motion must not become a second event store.
    assert hasattr(EvidenceSink, "append")
    assert not hasattr(EvidenceSink, "get")
