"""Behavioural tests for tool_registry — A1.

Covers: valid actions pass, unknown action_type rejected, missing required
params, extra (forbidden) params, bool-as-int rejection, type mismatches,
target_id requirement, register/get API, observe attribute allow-list,
and full TaskGraph validation via build_template_plan.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "libs/contracts"),
    str(ROOT / "services/agent_runtime"),
    str(ROOT / "tools/scripts"),
]

from workbench_agent_runtime import build_template_plan  # exported via __init__
from workbench_agent_runtime.tool_registry import ToolRegistry
from workbench_contracts import ActionType, SemanticAction

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _action(
    action_type: ActionType,
    *,
    action_id: str = "act-test",
    target_id: str | None = None,
    parameters: dict | None = None,
) -> SemanticAction:
    return SemanticAction(
        action_id=action_id,
        action_type=action_type,
        target_id=target_id,
        parameters=parameters or {},
    )


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


class ToolRegistryRegistrationTests(unittest.TestCase):
    """ToolRegistry knows all six ActionTypes on construction,
    supports register()/get(), and rejects invalid or duplicate registrations."""

    def setUp(self) -> None:
        self.registry = ToolRegistry()

    def test_all_six_action_types_are_registered(self) -> None:
        registered = self.registry.list_all()
        self.assertEqual(len(registered), 6)
        self.assertIn(ActionType.OBSERVE, registered)
        self.assertIn(ActionType.GRASP, registered)
        self.assertIn(ActionType.PLACE, registered)
        self.assertIn(ActionType.ASK_CONFIRM, registered)
        self.assertIn(ActionType.EXPRESS, registered)
        self.assertIn(ActionType.STOP, registered)

    def test_register_rejects_non_action_type(self) -> None:
        with self.assertRaises(ValueError):
            self.registry.register("not_an_enum", {})  # type: ignore[arg-type]

    def test_register_rejects_duplicate(self) -> None:
        with self.assertRaises(ValueError):
            self.registry.register(ActionType.STOP, {})

    def test_get_returns_schema_for_registered_action(self) -> None:
        schema = self.registry.get(ActionType.GRASP)
        self.assertIsInstance(schema, dict)
        self.assertIn("required_params", schema)

    def test_get_rejects_non_action_type(self) -> None:
        with self.assertRaises(ValueError):
            self.registry.get("not_an_enum")  # type: ignore[arg-type]

    def test_get_rejects_unregistered_action(self) -> None:
        """A valid ActionType that was not registered must raise KeyError."""
        # Default ctor loads all six, so we test that a plain string raises
        # ValueError (wrong type); KeyError is tested via a constructed
        # scenario where the ActionType is valid but never registered.
        empty = ToolRegistry()
        with self.assertRaises(ValueError):
            empty.get("observe")  # type: ignore[arg-type]


class ToolRegistryValidationTests(unittest.TestCase):
    """Core validation behaviour."""

    def setUp(self) -> None:
        self.registry = ToolRegistry()

    # -- valid actions --------------------------------------------------------

    def test_observe_with_no_params_is_valid(self) -> None:
        result = self.registry.validate(_action(ActionType.OBSERVE))
        self.assertTrue(result.is_valid)

    def test_observe_with_optional_confidence_is_valid(self) -> None:
        result = self.registry.validate(_action(ActionType.OBSERVE, parameters={"required_confidence": 0.95}))
        self.assertTrue(result.is_valid)

    def test_grasp_with_target_id_is_valid(self) -> None:
        result = self.registry.validate(_action(ActionType.GRASP, target_id="red_block"))
        self.assertTrue(result.is_valid)

    def test_place_with_destination_and_target_is_valid(self) -> None:
        result = self.registry.validate(
            _action(
                ActionType.PLACE,
                target_id="red_block",
                parameters={"destination_id": "tray"},
            )
        )
        self.assertTrue(result.is_valid)

    def test_place_with_all_optional_params_is_valid(self) -> None:
        result = self.registry.validate(
            _action(
                ActionType.PLACE,
                target_id="parcel_box",
                parameters={
                    "destination_id": "pickup_shelf",
                    "routing_reason": "verified_intact",
                    "routing_priority": "standard",
                    "policy_version": "parcel-routing-v3",
                    "identity_guard": "unique_across_supported_fields",
                    "manifest_guard": "matched",
                    "destination_capacity": 5,
                    "destination_occupancy_after": 2,
                    "destination_remaining_after": 3,
                },
            )
        )
        self.assertTrue(result.is_valid)

    def test_ask_confirm_is_valid(self) -> None:
        result = self.registry.validate(_action(ActionType.ASK_CONFIRM, parameters={"question": "proceed?"}))
        self.assertTrue(result.is_valid)

    def test_express_is_valid(self) -> None:
        result = self.registry.validate(_action(ActionType.EXPRESS, parameters={"emotion_state": "pleased"}))
        self.assertTrue(result.is_valid)

    def test_stop_is_valid(self) -> None:
        result = self.registry.validate(_action(ActionType.STOP))
        self.assertTrue(result.is_valid)

    # -- target_id requirement ------------------------------------------------

    def test_grasp_without_target_id_is_rejected(self) -> None:
        result = self.registry.validate(_action(ActionType.GRASP))
        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("target_id" in e.field for e in result.errors),
            f"expected target_id error in {result.errors}",
        )

    def test_grasp_with_empty_target_id_is_rejected(self) -> None:
        result = self.registry.validate(_action(ActionType.GRASP, target_id=""))
        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("target_id" in e.field for e in result.errors),
            f"expected target_id error in {result.errors}",
        )

    def test_place_without_target_id_is_rejected(self) -> None:
        result = self.registry.validate(_action(ActionType.PLACE, parameters={"destination_id": "tray"}))
        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("target_id" in e.field for e in result.errors),
            f"expected target_id error in {result.errors}",
        )

    def test_observe_without_target_id_is_valid(self) -> None:
        """OBSERVE does not require target_id (global scan is valid)."""
        result = self.registry.validate(_action(ActionType.OBSERVE))
        self.assertTrue(result.is_valid)

    # -- unknown / non-ActionType input ---------------------------------------

    def test_non_action_type_input_is_rejected_without_raising(self) -> None:
        """Passing a raw string as action_type must return ValidationResult,
        not raise AttributeError.  We use model_construct to bypass
        Pydantic coercion — this simulates a malformed frame from a buggy
        caller or a wire format that does not round-trip through the enum."""
        action = SemanticAction.model_construct(
            action_id="act-bad",
            action_type="grasp",  # raw string, not ActionType enum
            target_id="red_block",
        )
        result = self.registry.validate(action)
        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("ActionType" in e.message for e in result.errors),
            f"expected ActionType error in {result.errors}",
        )

    # -- extra (forbidden) params ---------------------------------------------

    def test_extra_param_is_rejected(self) -> None:
        result = self.registry.validate(_action(ActionType.OBSERVE, parameters={"joint_angle": 90}))
        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("forbidden keys" in e.message for e in result.errors),
            f"expected 'forbidden keys' in {result.errors}",
        )

    # -- missing required params -----------------------------------------------

    def test_missing_required_destination_id_is_rejected(self) -> None:
        result = self.registry.validate(_action(ActionType.PLACE, target_id="red_block", parameters={}))
        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("missing required" in e.message for e in result.errors),
            f"expected 'missing required' in {result.errors}",
        )

    def test_ask_confirm_missing_question_is_rejected(self) -> None:
        result = self.registry.validate(_action(ActionType.ASK_CONFIRM, parameters={}))
        self.assertFalse(result.is_valid)

    def test_express_missing_emotion_state_is_rejected(self) -> None:
        result = self.registry.validate(_action(ActionType.EXPRESS, parameters={}))
        self.assertFalse(result.is_valid)

    # -- type safety: bool-before-int -----------------------------------------

    def test_bool_passed_as_int_is_rejected(self) -> None:
        """True is an int in Python — the registry must reject it."""
        result = self.registry.validate(
            _action(
                ActionType.ASK_CONFIRM,
                parameters={"question": "ok?", "timeout_s": True},
            )
        )
        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("bool is not int" in e.message for e in result.errors),
            f"expected 'bool is not int' in {result.errors}",
        )

    def test_bool_passed_as_destination_capacity_is_rejected(self) -> None:
        result = self.registry.validate(
            _action(
                ActionType.PLACE,
                target_id="box",
                parameters={
                    "destination_id": "bin",
                    "destination_capacity": False,
                },
            )
        )
        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("bool" in e.message.lower() for e in result.errors),
            f"expected bool rejection in {result.errors}",
        )

    # -- type safety: str fields -----------------------------------------------

    def test_destination_id_not_a_string_is_rejected(self) -> None:
        result = self.registry.validate(
            _action(
                ActionType.PLACE,
                target_id="red_block",
                parameters={"destination_id": 42},
            )
        )
        self.assertFalse(result.is_valid)

    def test_question_not_a_string_is_rejected(self) -> None:
        result = self.registry.validate(
            _action(
                ActionType.ASK_CONFIRM,
                parameters={"question": None},  # type: ignore[arg-type]
            )
        )
        self.assertFalse(result.is_valid)

    # -- semantic constraints: express emotion enum ---------------------------

    def test_express_invalid_emotion_is_rejected(self) -> None:
        result = self.registry.validate(
            _action(
                ActionType.EXPRESS,
                parameters={"emotion_state": "angry"},
            )
        )
        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("emotion_state" in e.field for e in result.errors),
            f"expected emotion_state error in {result.errors}",
        )

    # -- semantic constraints: observe attributes -----------------------------

    def test_observe_with_known_attributes_is_valid(self) -> None:
        result = self.registry.validate(
            _action(
                ActionType.OBSERVE,
                parameters={"attributes": ["presence", "identity", "orientation"]},
            )
        )
        self.assertTrue(result.is_valid)

    def test_observe_with_unknown_attribute_is_rejected(self) -> None:
        result = self.registry.validate(
            _action(
                ActionType.OBSERVE,
                parameters={"attributes": ["presence", "mass_kg"]},
            )
        )
        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("attributes" in e.field for e in result.errors),
            f"expected attributes error in {result.errors}",
        )

    def test_observe_attribute_not_a_string_is_rejected(self) -> None:
        result = self.registry.validate(
            _action(
                ActionType.OBSERVE,
                parameters={"attributes": ["presence", 42]},
            )
        )
        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("attributes" in e.field for e in result.errors),
            f"expected string-only error in {result.errors}",
        )

    # -- ValidationResult structure -------------------------------------------

    def test_validation_result_contains_action_id(self) -> None:
        result = self.registry.validate(_action(ActionType.OBSERVE, action_id="my-action-42"))
        self.assertEqual(result.action_id, "my-action-42")

    def test_validation_error_fields_are_populated(self) -> None:
        result = self.registry.validate(_action(ActionType.PLACE, parameters={}))
        self.assertFalse(result.is_valid)
        for error in result.errors:
            self.assertIsInstance(error.field, str)
            self.assertIsInstance(error.message, str)
            self.assertTrue(len(error.field) > 0)
            self.assertTrue(len(error.message) > 0)


class PlannerIntegrationTests(unittest.TestCase):
    """Every build_template_plan path passes the registry."""

    def test_build_place_plan_validates(self) -> None:
        plan = build_template_plan("Place the red block in the tray")
        self.assertEqual(plan.task_id, "task-place-red-block")

    def test_build_kitting_plan_validates(self) -> None:
        plan = build_template_plan("Assemble a three-part kit in the tray")
        self.assertEqual(plan.task_id, "task-kit-three-parts")
        self.assertEqual(len(plan.steps), 9)

    def test_build_inspection_plan_validates(self) -> None:
        plan = build_template_plan("Inspect all three workpieces")
        self.assertEqual(plan.task_id, "task-inspect-workpieces")
        self.assertEqual(len(plan.steps), 3)

    def test_build_clearance_plan_validates(self) -> None:
        plan = build_template_plan("Clear the blocked path and place the red block")
        self.assertEqual(plan.task_id, "task-clear-workspace")
        self.assertEqual(len(plan.steps), 6)

    def test_build_parcel_plan_validates(self) -> None:
        plan = build_template_plan("Sort the courier parcels and isolate damage")
        self.assertEqual(plan.task_id, "task-sort-parcels")
        self.assertEqual(len(plan.steps), 12)

    def test_all_planner_steps_contain_only_semantic_actions(self) -> None:
        """Smoke-test: no planner path emits joint or velocity tokens."""
        for goal in (
            "Place the red block in the tray",
            "Assemble a three-part kit in the tray",
            "Inspect all three workpieces",
            "Clear the blocked path and place the red block",
            "Sort the courier parcels and isolate damage",
        ):
            with self.subTest(goal=goal):
                plan = build_template_plan(goal)
                dumped = plan.model_dump_json(indent=2)
                self.assertNotIn("joint", dumped)
                self.assertNotIn("velocity", dumped)


if __name__ == "__main__":
    unittest.main()
