import json
import tempfile
from pathlib import Path

from _paths import enable_local_packages

enable_local_packages()

from workbench_agent_runtime import build_template_plan
from workbench_contracts import WorldEvent, WorldEventType
from workbench_virtual_mcu import VirtualMcu
from workbench_world_model import SQLiteEventStore, reduce_events, verify_object_in_tray


def event(
    event_id: str,
    sequence_no: int,
    event_type: WorldEventType,
    payload: dict,
    evidence: list[str],
) -> WorldEvent:
    return WorldEvent(
        event_id=event_id,
        run_id="dry-run-001",
        sequence_no=sequence_no,
        event_type=event_type,
        occurred_at="2026-08-04T00:00:00Z",
        payload=payload,
        evidence_refs=evidence,
    )


def main() -> int:
    plan = build_template_plan("Place the red block in the tray")
    mcu = VirtualMcu()
    mcu.command("execute")
    events = [
        event(
            "evt-001",
            1,
            WorldEventType.OBSERVATION,
            {"entity_id": "red_block", "location": "table", "confidence": 0.98},
            ["camera-frame-001"],
        ),
        event(
            "evt-002",
            2,
            WorldEventType.OBSERVATION,
            {"entity_id": "tray", "location": "table", "confidence": 0.99},
            ["camera-frame-002"],
        ),
        event(
            "evt-003",
            3,
            WorldEventType.ACTION_RESULT,
            {"outcome": "completed", "entity_id": "red_block", "resulting_location": "in:tray"},
            ["action-result-003"],
        ),
    ]
    with tempfile.TemporaryDirectory() as directory:
        store = SQLiteEventStore(Path(directory) / "events.sqlite")
        for item in events:
            store.append(item)
        state = reduce_events("dry-run-001", store.list_run("dry-run-001"))
        verification = verify_object_in_tray(state, plan.task_id, "red_block", "tray")
        store.close()
    if verification.completed:
        mcu.command("complete")

    output = {
        "task_id": plan.task_id,
        "steps": [step.action.action_type.value for step in plan.steps],
        "mcu_state": mcu.state.value,
        "verified_complete": verification.completed,
        "evidence_refs": verification.evidence_refs,
    }
    if not verification.completed:
        raise RuntimeError("dry run failed verification")
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
