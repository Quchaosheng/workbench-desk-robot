"""Behavioural tests for policy_validator — A5.

Covers exact field-set equality (reject extra AND missing), bool-before-int
(duration_ms and other integer slots), type mismatches, fail-closed enforcement,
TaskGraph-level aggregation, non-ActionType input, target_id requirement, and
the rule that the validator never emits a VerificationResult.
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

from workbench_agent_runtime.policy_validator import (
    PolicyFinding,
    PolicyReport,
    PolicyValidator,
    PolicyViolation,
)
from workbench_agent_runtime.tool_registry import ToolRegistry
from workbench_contracts import ActionType, SemanticAction, TaskGraph, TaskStep

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


def _graph(*actions: SemanticAction) -> TaskGraph:
    steps = [TaskStep(step_id=f"step-{index}", action=action) for index, action in enumerate(actions, start=1)]
    return TaskGraph(task_id="task-test", goal="test", steps=steps, planner="test")


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


class PolicyValidatorValidActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = PolicyValidator()

    def test_observe_with_no_params_is_valid(self) -> None:
        report = self.validator.check(_graph(_action(ActionType.OBSERVE)))
        self.assertTrue(report.is_valid)

    def test_grasp_with_target_id_is_valid(self) -> None:
        report = self.validator.check(_graph(_action(ActionType.GRASP, target_id="red_block")))
        self.assertTrue(report.is_valid)

    def test_place_with_destination_is_valid(self) -> None:
        report = self.validator.check(
            _graph(
                _action(
                    ActionType.PLACE,
                    target_id="red_block",
                    parameters={"destination_id": "tray"},
                )
            )
        )
        self.assertTrue(report.is_valid)

    def test_ask_confirm_is_valid(self) -> None:
        report = self.validator.check(_graph(_action(ActionType.ASK_CONFIRM, parameters={"question": "proceed?"})))
        self.assertTrue(report.is_valid)

    def test_express_is_valid(self) -> None:
        report = self.validator.check(_graph(_action(ActionType.EXPRESS, parameters={"emotion_state": "pleased"})))
        self.assertTrue(report.is_valid)

    def test_stop_is_valid(self) -> None:
        report = self.validator.check(_graph(_action(ActionType.STOP)))
        self.assertTrue(report.is_valid)


class PolicyValidatorFieldSetTests(unittest.TestCase):
    """Exact field-set equality: reject extra AND missing."""

    def setUp(self) -> None:
        self.validator = PolicyValidator()

    def test_extra_field_is_rejected(self) -> None:
        report = self.validator.check(_graph(_action(ActionType.OBSERVE, parameters={"joint_angle": 90})))
        self.assertFalse(report.is_valid)
        self.assertTrue(any("forbidden keys" in f.message for f in report.findings))

    def test_missing_required_field_is_rejected(self) -> None:
        report = self.validator.check(_graph(_action(ActionType.PLACE, target_id="red_block", parameters={})))
        self.assertFalse(report.is_valid)
        self.assertTrue(any("missing required" in f.message for f in report.findings))

    def test_exact_field_set_equality_is_not_subset(self) -> None:
        """A subset of allowed params that omits a required key must be rejected.

        This is the A5 acceptance point: the field set must be EXACTLY equal to
        the whitelist requirement, not merely a subset of the allow-list."""
        # place requires destination_id; omitting it leaves a subset -> reject
        report = self.validator.check(
            _graph(
                _action(
                    ActionType.PLACE,
                    target_id="red_block",
                    parameters={"routing_reason": "verified_intact"},
                )
            )
        )
        self.assertFalse(report.is_valid)
        self.assertTrue(any("missing required" in f.message for f in report.findings))

    def test_optional_fields_may_be_absent(self) -> None:
        """Optional fields are not required; their absence must not fail."""
        report = self.validator.check(_graph(_action(ActionType.ASK_CONFIRM, parameters={"question": "ok?"})))
        self.assertTrue(report.is_valid)


class PolicyValidatorBoolBeforeIntTests(unittest.TestCase):
    """bool must be rejected for integer slots, not coerced to 1/0."""

    def setUp(self) -> None:
        self.validator = PolicyValidator()

    def test_duration_ms_bool_is_rejected(self) -> None:
        report = self.validator.check(
            _graph(
                _action(
                    ActionType.EXPRESS,
                    parameters={"emotion_state": "pleased", "duration_ms": True},
                )
            )
        )
        self.assertFalse(report.is_valid)
        self.assertTrue(any("bool is not int" in f.message for f in report.findings))

    def test_timeout_s_bool_is_rejected(self) -> None:
        report = self.validator.check(
            _graph(
                _action(
                    ActionType.ASK_CONFIRM,
                    parameters={"question": "ok?", "timeout_s": False},
                )
            )
        )
        self.assertFalse(report.is_valid)
        self.assertTrue(any("bool is not int" in f.message for f in report.findings))

    def test_destination_capacity_bool_is_rejected(self) -> None:
        report = self.validator.check(
            _graph(
                _action(
                    ActionType.PLACE,
                    target_id="box",
                    parameters={"destination_id": "bin", "destination_capacity": True},
                )
            )
        )
        self.assertFalse(report.is_valid)
        self.assertTrue(any("bool" in f.message.lower() for f in report.findings))

    def test_genuine_integer_is_accepted(self) -> None:
        report = self.validator.check(
            _graph(
                _action(
                    ActionType.EXPRESS,
                    parameters={"emotion_state": "pleased", "duration_ms": 500},
                )
            )
        )
        self.assertTrue(report.is_valid)


class PolicyValidatorTypeMismatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = PolicyValidator()

    def test_str_slot_with_int_is_rejected(self) -> None:
        report = self.validator.check(
            _graph(
                _action(
                    ActionType.PLACE,
                    target_id="red_block",
                    parameters={"destination_id": 42},
                )
            )
        )
        self.assertFalse(report.is_valid)
        self.assertTrue(any("expected str" in f.message for f in report.findings))

    def test_float_slot_with_str_is_rejected(self) -> None:
        report = self.validator.check(
            _graph(
                _action(
                    ActionType.OBSERVE,
                    parameters={"required_confidence": "high"},
                )
            )
        )
        self.assertFalse(report.is_valid)
        self.assertTrue(any("expected float" in f.message for f in report.findings))


class PolicyValidatorEnforcementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = PolicyValidator()

    def test_enforce_raises_on_invalid_graph(self) -> None:
        with self.assertRaises(PolicyViolation):
            self.validator.enforce(_graph(_action(ActionType.PLACE, target_id="red_block", parameters={})))

    def test_enforce_passes_valid_graph(self) -> None:
        self.validator.enforce(
            _graph(
                _action(
                    ActionType.PLACE,
                    target_id="red_block",
                    parameters={"destination_id": "tray"},
                )
            )
        )

    def test_enforce_message_locates_step_and_field(self) -> None:
        with self.assertRaises(PolicyViolation) as context:
            self.validator.enforce(_graph(_action(ActionType.GRASP, parameters={})))
        message = str(context.exception)
        self.assertIn("step 'step-1'", message)
        self.assertIn("target_id", message)


class PolicyValidatorAggregationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = PolicyValidator()

    def test_multiple_invalid_steps_aggregate_all_findings(self) -> None:
        graph = _graph(
            _action(ActionType.GRASP, action_id="act-1", parameters={}),
            _action(
                ActionType.PLACE,
                action_id="act-2",
                target_id="red_block",
                parameters={},
            ),
        )
        report = self.validator.check(graph)
        self.assertFalse(report.is_valid)
        self.assertEqual(len(report.findings), 2)

    def test_single_step_with_multiple_errors_reports_all(self) -> None:
        # missing destination_id AND forbidden key on the same action
        report = self.validator.check(
            _graph(
                _action(
                    ActionType.PLACE,
                    target_id="red_block",
                    parameters={"joint_angle": 90},
                )
            )
        )
        self.assertFalse(report.is_valid)
        self.assertEqual(len(report.findings), 2)


class PolicyValidatorBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = PolicyValidator()

    def test_non_action_type_input_is_rejected(self) -> None:
        action = SemanticAction.model_construct(
            action_id="act-bad",
            action_type="grasp",  # raw string, bypasses Pydantic coercion
            target_id="red_block",
        )
        report = self.validator.check(_graph(action))
        self.assertFalse(report.is_valid)
        self.assertTrue(any("ActionType" in f.message for f in report.findings))

    def test_grasp_without_target_id_is_rejected(self) -> None:
        report = self.validator.check(_graph(_action(ActionType.GRASP)))
        self.assertFalse(report.is_valid)
        self.assertTrue(any(f.field == "target_id" for f in report.findings))

    def test_empty_task_graph_is_valid(self) -> None:
        """Structural minItems is Pydantic's job; the validator passes empty."""
        report = self.validator.check(TaskGraph(task_id="task-empty", goal="test", steps=[], planner="test"))
        self.assertTrue(report.is_valid)

    def test_validator_uses_injected_registry(self) -> None:
        """The validator must read its whitelist from the injected registry,
        not a hardcoded second copy."""
        empty_registry = ToolRegistry(load_defaults=False)
        validator = PolicyValidator(registry=empty_registry)
        report = validator.check(_graph(_action(ActionType.OBSERVE)))
        self.assertFalse(report.is_valid)  # nothing registered -> reject


class PolicyValidatorRuleBoundaryTests(unittest.TestCase):
    def test_validator_does_not_emit_verification_result(self) -> None:
        """Rule 2: completion is judged only by the world-model verifier.
        The validator's output must be a PolicyReport, never a VerificationResult."""
        validator = PolicyValidator()
        report = validator.check(_graph(_action(ActionType.OBSERVE)))
        self.assertIsInstance(report, PolicyReport)
        self.assertIsInstance(report.findings, tuple)
        # No VerificationResult is constructed anywhere in this path.
        from workbench_contracts import VerificationResult

        self.assertNotIsInstance(report, VerificationResult)

    def test_report_findings_are_policy_findings(self) -> None:
        validator = PolicyValidator()
        report = validator.check(_graph(_action(ActionType.GRASP)))
        for finding in report.findings:
            self.assertIsInstance(finding, PolicyFinding)
            self.assertIsInstance(finding.step_id, str)
            self.assertIsInstance(finding.field, str)
            self.assertIsInstance(finding.message, str)


if __name__ == "__main__":
    unittest.main()
