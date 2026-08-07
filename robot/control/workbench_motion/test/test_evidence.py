"""Unit tests for the EvidenceSink interface and FakeEvidenceSink.

Proves the phase-0 acceptance criterion: ``append()`` returns a stable, unique
reference, and Motion holds no persistence implementation (no ``get`` on the
interface).
"""

from __future__ import annotations

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
    event = _event()
    try:
        event.action_id = "mutated"  # type: ignore[misc]
    except Exception:  # noqa: BLE001 - frozen dataclass raises FrozenInstanceError
        pass
    else:
        raise AssertionError("ExecutionEvent must be frozen/immutable")


def test_motion_side_holds_no_read_api() -> None:
    # Enforce the boundary: the interface Motion talks to exposes append only,
    # never a get/query. Motion must not become a second event store.
    assert hasattr(EvidenceSink, "append")
    assert not hasattr(EvidenceSink, "get")
