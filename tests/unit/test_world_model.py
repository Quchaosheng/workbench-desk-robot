import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "libs/contracts"), str(ROOT / "services/world_model")]

from workbench_contracts import ReasonCode, VerificationStatus, WorldEvent, WorldEventType
from workbench_world_model import (
    apply_event,
    reduce_events,
    verify_inspection_evidence,
    verify_kit_contents,
    verify_object_in_tray,
    verify_workspace_clearance,
)
from workbench_world_model.reducer import WorldState


def placed_event() -> WorldEvent:
    return WorldEvent(
        event_id="evt-place",
        run_id="run-001",
        sequence_no=1,
        event_type=WorldEventType.ACTION_RESULT,
        occurred_at="2026-08-04T00:00:00Z",
        payload={"outcome": "completed", "entity_id": "red_block", "resulting_location": "in:tray"},
        evidence_refs=["act-001"],
    )


class WorldModelTests(unittest.TestCase):
    def test_event_is_idempotent(self) -> None:
        state = WorldState(run_id="run-001")
        once = apply_event(state, placed_event())
        twice = apply_event(once, placed_event())
        self.assertEqual(once.model_dump(), twice.model_dump())
        self.assertEqual(once.entity_evidence_refs["red_block"], ["act-001"])

    def test_verifier_uses_state_relation(self) -> None:
        state = reduce_events("run-001", [placed_event()])
        result = verify_object_in_tray(state, "task-001", "red_block", "tray")
        self.assertTrue(result.completed)
        state.evidence_refs.clear()
        state.entity_evidence_refs.clear()
        result = verify_object_in_tray(state, "task-001", "red_block", "tray")
        self.assertFalse(result.completed)
        self.assertEqual(result.status, VerificationStatus.INSUFFICIENT_EVIDENCE)
        self.assertEqual(result.reason_code, ReasonCode.EVIDENCE_MISSING)
        self.assertIn("no evidence", result.claim)

    def test_kitting_verifier_checks_all_parts_extras_confidence_and_evidence(self) -> None:
        state = WorldState(
            run_id="kit-run",
            entity_locations={
                "red_block": "in:kit_tray",
                "blue_cylinder": "in:kit_tray",
                "green_gear": "in:kit_tray",
            },
            entity_confidence={"red_block": 0.96, "blue_cylinder": 0.94, "green_gear": 0.91},
            entity_evidence_refs={
                "red_block": ["frame://kit/red"],
                "blue_cylinder": ["frame://kit/blue"],
                "green_gear": ["frame://kit/green"],
            },
            evidence_refs=["frame://kit/final"],
        )
        required = ["red_block", "blue_cylinder", "green_gear"]
        self.assertTrue(verify_kit_contents(state, "task-kit-three-parts", required).completed)
        state.entity_locations["wrong_part"] = "in:kit_tray"
        result = verify_kit_contents(state, "task-kit-three-parts", required)
        self.assertFalse(result.completed)
        self.assertEqual(result.status, VerificationStatus.REFUTED)
        self.assertIn("wrong_part", result.claim)

        state.entity_locations.pop("wrong_part")
        state.entity_evidence_refs.pop("blue_cylinder")
        result = verify_kit_contents(state, "task-kit-three-parts", required)
        self.assertFalse(result.completed)
        self.assertEqual(result.status, VerificationStatus.INSUFFICIENT_EVIDENCE)
        self.assertIn("blue_cylinder", result.claim)

        for invalid_required in ([], ["red_block", "red_block"], [""]):
            with self.subTest(required=invalid_required), self.assertRaises(ValueError):
                verify_kit_contents(state, "task-kit-three-parts", invalid_required)
        with self.assertRaises(ValueError):
            verify_kit_contents(state, "task-kit-three-parts", required, confidence_threshold=1.1)

    def test_inspection_and_clearance_verifiers_require_evidence(self) -> None:
        inspection = WorldState(
            run_id="inspect-run",
            entity_locations={"red_block": "on:table", "blue_cylinder": "on:table"},
            entity_confidence={"red_block": 0.95, "blue_cylinder": 0.42},
            entity_evidence_refs={
                "red_block": ["frame://inspect/red"],
                "blue_cylinder": ["frame://inspect/blue"],
            },
            evidence_refs=["frame://inspect/001"],
        )
        result = verify_inspection_evidence(
            inspection,
            "task-inspect-workpieces",
            ["red_block", "blue_cylinder"],
        )
        self.assertFalse(result.completed)
        self.assertEqual(result.reason_code, ReasonCode.CONFIDENCE_BELOW_THRESHOLD)
        self.assertIn("blue_cylinder", result.claim)

        clearance = WorldState(
            run_id="clear-run",
            entity_locations={"blue_cylinder": "in:staging_bin", "red_block": "in:tray"},
            entity_evidence_refs={
                "blue_cylinder": ["frame://clear/blue"],
                "red_block": ["frame://clear/red"],
            },
            evidence_refs=["frame://clear/final"],
        )
        self.assertTrue(verify_workspace_clearance(clearance, "task-clear-workspace").completed)
        clearance.entity_evidence_refs.pop("red_block")
        self.assertFalse(verify_workspace_clearance(clearance, "task-clear-workspace").completed)


if __name__ == "__main__":
    unittest.main()
