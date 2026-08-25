from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "robot/control/workbench_motion"),
    str(ROOT / "libs/contracts"),
    str(ROOT / "services/world_model"),
]

from workbench_contracts import ActionResult
from workbench_motion.evidence import EvidenceSink, ExecutionEvent
from workbench_world_model.event_store import SQLiteEventStore
from workbench_world_model.motion_evidence_adapter import MotionEvidenceAdapter
from workbench_world_model.reducer import reduce_events


def motion_event(payload: dict[str, object] | None = None) -> ExecutionEvent:
    result_payload = payload or ActionResult(
        result_id="res-integration-001",
        action_id="act-integration-001",
        run_id="run-integration-001",
        outcome="completed",
        dispatch_state="sent",
        device_state="confirmed",
        started_at="2026-08-04T00:00:12.400Z",
        ended_at="2026-08-04T00:00:15.900Z",
        entity_id="red_block",
        resulting_location="in:tray",
        evidence_refs=["mcu-frame-0142", "mcu-frame-0143"],
    ).model_dump(mode="json")
    return ExecutionEvent(
        event_type="action_result",
        run_id="run-integration-001",
        action_id="act-integration-001",
        payload=result_payload,
    )


def test_motion_append_store_replay_and_lookup(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite")
    adapter = MotionEvidenceAdapter(store)
    original_payload = ActionResult(
        result_id="res-integration-001",
        action_id="act-integration-001",
        run_id="run-integration-001",
        outcome="completed",
        dispatch_state="sent",
        device_state="confirmed",
        started_at="2026-08-04T00:00:12.400Z",
        ended_at="2026-08-04T00:00:15.900Z",
        entity_id="red_block",
        resulting_location="in:tray",
        evidence_refs=["mcu-frame-0142", "mcu-frame-0143"],
    ).model_dump(mode="json")
    event = motion_event(original_payload)

    assert isinstance(adapter, EvidenceSink)
    reference = adapter.append(event)
    original_payload["resulting_location"] = "on:table"
    evidence_refs = original_payload["evidence_refs"]
    assert isinstance(evidence_refs, list)
    evidence_refs.append("mutated-after-event")

    replayed = store.list_run("run-integration-001")
    assert len(replayed) == 1
    assert adapter.resolve(reference) == replayed[0]
    state = reduce_events("run-integration-001", replayed)
    assert state.applied_event_ids == [replayed[0].event_id]
    assert state.evidence_refs == ["mcu-frame-0142", "mcu-frame-0143"]
    assert state.entity_locations == {}
    assert state.entity_evidence_refs == {}
    assert replayed[0].payload["resulting_location"] == "in:tray"
    assert replayed[0].evidence_refs == ["mcu-frame-0142", "mcu-frame-0143"]
    store.close()


def test_reopen_preserves_evidence_reference(tmp_path: Path) -> None:
    database_path = tmp_path / "events.sqlite"
    store = SQLiteEventStore(database_path)
    reference = MotionEvidenceAdapter(store).append(motion_event())
    store.close()

    reopened = SQLiteEventStore(database_path)
    resolved = MotionEvidenceAdapter(reopened).resolve(reference)

    assert resolved is not None
    assert resolved.event_id == "motion-result:run-integration-001:res-integration-001"
    assert resolved.payload["action_id"] == "act-integration-001"
    reopened.close()
