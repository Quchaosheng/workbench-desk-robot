import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "libs/contracts"), str(ROOT / "services/world_model")]

from workbench_contracts import WorldEvent, WorldEventType
from workbench_world_model import apply_event, reduce_events, verify_object_in_tray
from workbench_world_model.reducer import WorldState


def placed_event() -> WorldEvent:
    return WorldEvent(
        event_id="evt-place",
        run_id="run-001",
        sequence_no=1,
        event_type=WorldEventType.ACTION_RESULT,
        occurred_at="2026-08-04T00:00:00Z",
        payload={"status": "succeeded", "entity_id": "red_block", "resulting_location": "in:tray"},
        evidence_refs=["act-001"],
    )


class WorldModelTests(unittest.TestCase):
    def test_event_is_idempotent(self) -> None:
        state = WorldState(run_id="run-001")
        once = apply_event(state, placed_event())
        twice = apply_event(once, placed_event())
        self.assertEqual(once.model_dump(), twice.model_dump())

    def test_verifier_uses_state_relation(self) -> None:
        state = reduce_events("run-001", [placed_event()])
        result = verify_object_in_tray(state, "task-001", "red_block", "tray")
        self.assertTrue(result.completed)


if __name__ == "__main__":
    unittest.main()
