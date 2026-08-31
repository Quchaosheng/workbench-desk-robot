"""Behavioural tests for policy_validator — A5.

Covers exact field-set equality (reject extra AND missing), bool-before-int
(duration_ms and other integer slots), type mismatches, fail-closed enforcement,
TaskGraph-level aggregation, non-ActionType input, target_id requirement, and
the rule that the validator never emits a VerificationResult.
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "libs/contracts"),
    str(ROOT / "services/agent_runtime"),
    str(ROOT / "tools/scripts"),
]

from pydantic import ValidationError
from workbench_agent_runtime.policy_validator import (
    PolicyFinding,
    PolicyReport,
    PolicyValidator,
    PolicyViolation,
)
from workbench_agent_runtime.tool_registry import ToolRegistry
from workbench_agent_runtime.tool_schemas import TOOL_SCHEMAS
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
    return TaskGraph(task_id="task-test", goal="test", steps=steps, planner="test", model_route="template")


POLICY_VERSION = "test-policy-v1"


def _policy_config(*, high_impact_actions: frozenset[ActionType] = frozenset()) -> dict[str, object]:
    return {
        "policy_version": POLICY_VERSION,
        "high_impact_actions": high_impact_actions,
    }


def _validator(
    registry: ToolRegistry | None = None,
    *,
    high_impact_actions: frozenset[ActionType] = frozenset(),
) -> PolicyValidator:
    return PolicyValidator(
        registry=registry,
        policy_config=_policy_config(high_impact_actions=high_impact_actions),
    )


def _registry_with_stop_parameter(name: str, parameter_type: type) -> ToolRegistry:
    schema = dict(TOOL_SCHEMAS[ActionType.STOP])
    schema["optional_params"] = schema["optional_params"] | frozenset({name})
    schema["param_types"] = {**schema["param_types"], name: parameter_type}
    registry = ToolRegistry(load_defaults=False)
    registry.register(ActionType.STOP, schema)
    return registry


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


class PolicyValidatorValidActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = _validator()

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
        self.validator = _validator()

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
        self.validator = _validator()

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


class PolicyValidatorSchemaConstraintTests(unittest.TestCase):
    """A5 consumes value and relational constraints from ToolRegistry."""

    def setUp(self) -> None:
        self.validator = _validator()

    def test_non_finite_confidence_is_rejected(self) -> None:
        report = self.validator.check(
            _graph(_action(ActionType.OBSERVE, parameters={"required_confidence": float("nan")}))
        )
        self.assertFalse(report.is_valid)
        self.assertTrue(any("finite" in finding.message for finding in report.findings))

    def test_blank_question_and_out_of_range_timeout_are_rejected(self) -> None:
        report = self.validator.check(
            _graph(_action(ActionType.ASK_CONFIRM, parameters={"question": " ", "timeout_s": 601}))
        )
        self.assertFalse(report.is_valid)
        self.assertEqual(
            {finding.field for finding in report.findings},
            {"parameters.question", "parameters.timeout_s"},
        )

    def test_inconsistent_destination_snapshot_is_rejected(self) -> None:
        report = self.validator.check(
            _graph(
                _action(
                    ActionType.PLACE,
                    target_id="parcel",
                    parameters={
                        "destination_id": "bin",
                        "destination_capacity": 5,
                        "destination_occupancy_after": 2,
                        "destination_remaining_after": 2,
                    },
                )
            )
        )
        self.assertFalse(report.is_valid)
        self.assertTrue(any("capacity = occupancy_after" in finding.message for finding in report.findings))

    def test_valid_constraint_boundaries_are_accepted(self) -> None:
        report = self.validator.check(
            _graph(
                _action(ActionType.OBSERVE, parameters={"required_confidence": 1.0}),
                _action(ActionType.ASK_CONFIRM, parameters={"question": "continue?", "timeout_s": 600}),
                _action(ActionType.EXPRESS, parameters={"emotion_state": "pleased", "duration_ms": 600000}),
                _action(
                    ActionType.PLACE,
                    target_id="parcel",
                    parameters={
                        "destination_id": "bin",
                        "destination_capacity": 0,
                        "destination_occupancy_after": 0,
                        "destination_remaining_after": 0,
                    },
                ),
            )
        )
        self.assertTrue(report.is_valid, report.findings)


class PolicyValidatorTypeMismatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = _validator()

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
        self.validator = _validator()

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
        self.validator = _validator()

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
        self.validator = _validator()

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

    def test_empty_task_graph_is_rejected_at_contract_boundary(self) -> None:
        with self.assertRaises(ValidationError):
            TaskGraph(task_id="task-empty", goal="test", steps=[], planner="test", model_route="template")

    def test_validator_uses_injected_registry(self) -> None:
        """The validator must read its whitelist from the injected registry,
        not a hardcoded second copy."""
        empty_registry = ToolRegistry(load_defaults=False)
        validator = _validator(registry=empty_registry)
        report = validator.check(_graph(_action(ActionType.OBSERVE)))
        self.assertFalse(report.is_valid)  # nothing registered -> reject


class PolicyValidatorRuleBoundaryTests(unittest.TestCase):
    def test_validator_does_not_emit_verification_result(self) -> None:
        """Rule 2: completion is judged only by the world-model verifier.
        The validator's output must be a PolicyReport, never a VerificationResult."""
        validator = _validator()
        report = validator.check(_graph(_action(ActionType.OBSERVE)))
        self.assertIsInstance(report, PolicyReport)
        self.assertIsInstance(report.findings, tuple)
        # No VerificationResult is constructed anywhere in this path.
        from workbench_contracts import VerificationResult

        self.assertNotIsInstance(report, VerificationResult)

    def test_report_findings_are_policy_findings(self) -> None:
        validator = _validator()
        report = validator.check(_graph(_action(ActionType.GRASP)))
        for finding in report.findings:
            self.assertIsInstance(finding, PolicyFinding)
            self.assertIsInstance(finding.step_id, str)
            self.assertIsInstance(finding.field, str)
            self.assertIsInstance(finding.message, str)


class PolicyValidatorConfigurationTests(unittest.TestCase):
    def test_missing_policy_config_fails_closed(self) -> None:
        report = PolicyValidator().check(_graph(_action(ActionType.OBSERVE)))

        self.assertFalse(report.is_valid)
        self.assertEqual(report.decisions[0].outcome, "deny")
        self.assertEqual(report.decisions[0].reason_code, "policy_config_missing")
        self.assertIsNone(report.decisions[0].policy_version)

    def test_blank_policy_version_fails_closed(self) -> None:
        validator = PolicyValidator(
            policy_config={
                "policy_version": "  ",
                "high_impact_actions": frozenset(),
            }
        )

        report = validator.check(_graph(_action(ActionType.OBSERVE)))

        self.assertFalse(report.is_valid)
        self.assertEqual(report.decisions[0].reason_code, "policy_version_blank")
        self.assertIsNone(report.decisions[0].policy_version)

    def test_unknown_high_impact_action_fails_closed(self) -> None:
        validator = PolicyValidator(
            policy_config={
                "policy_version": POLICY_VERSION,
                "high_impact_actions": frozenset({"joint_move"}),
            }
        )

        report = validator.check(_graph(_action(ActionType.OBSERVE)))

        self.assertFalse(report.is_valid)
        self.assertEqual(report.decisions[0].reason_code, "policy_config_unknown_action")
        self.assertEqual(report.decisions[0].policy_version, POLICY_VERSION)

    def test_malformed_policy_config_fails_closed(self) -> None:
        malformed_configs = (
            object(),
            {"policy_version": POLICY_VERSION},
            {"policy_version": 1, "high_impact_actions": frozenset()},
            {"policy_version": POLICY_VERSION, "high_impact_actions": [ActionType.PLACE]},
            {
                "policy_version": POLICY_VERSION,
                "high_impact_actions": frozenset(),
                "unexpected": True,
            },
        )
        for config in malformed_configs:
            with self.subTest(config=config):
                report = PolicyValidator(policy_config=config).check(_graph(_action(ActionType.OBSERVE)))
                self.assertFalse(report.is_valid)
                self.assertEqual(report.decisions[0].reason_code, "policy_config_malformed")


class PolicyValidatorStructuredDecisionTests(unittest.TestCase):
    def test_safe_action_is_allowed_with_versioned_structured_reason_without_mutation(self) -> None:
        action = _action(ActionType.OBSERVE, action_id="act-safe", parameters={"required_confidence": 0.9})
        graph = _graph(action)
        action_before = action.model_dump_json().encode()
        graph_before = graph.model_dump_json().encode()

        report = _validator().check(graph)

        self.assertTrue(report.is_valid)
        self.assertEqual(len(report.decisions), 1)
        decision = report.decisions[0]
        self.assertEqual(decision.step_id, "step-1")
        self.assertEqual(decision.action_id, "act-safe")
        self.assertEqual(decision.outcome, "allow")
        self.assertEqual(decision.reason_code, "policy_allowed")
        self.assertEqual(decision.policy_version, POLICY_VERSION)
        self.assertEqual(action.model_dump_json().encode(), action_before)
        self.assertEqual(graph.model_dump_json().encode(), graph_before)
        self.assertIsInstance(report.decisions, tuple)
        with self.assertRaises(FrozenInstanceError):
            decision.outcome = "deny"

    def test_unknown_action_is_denied_structurally(self) -> None:
        registry = ToolRegistry(load_defaults=False)

        report = _validator(registry=registry).check(_graph(_action(ActionType.OBSERVE, action_id="act-unknown")))

        self.assertFalse(report.is_valid)
        decision = report.decisions[0]
        self.assertEqual(decision.step_id, "step-1")
        self.assertEqual(decision.action_id, "act-unknown")
        self.assertEqual(decision.outcome, "deny")
        self.assertEqual(decision.reason_code, "tool_registry_denied")
        self.assertEqual(decision.policy_version, POLICY_VERSION)
        self.assertTrue(any(finding.field == "action_type" for finding in decision.findings))

    def test_injected_registry_change_propagates_without_second_allowlist(self) -> None:
        registry = _registry_with_stop_parameter("operator_note", str)
        graph = _graph(
            _action(
                ActionType.STOP,
                action_id="act-custom",
                parameters={"operator_note": "approved semantic stop"},
            )
        )

        report = _validator(registry=registry).check(graph)

        self.assertTrue(report.is_valid, report.decisions)
        self.assertEqual(report.decisions[0].outcome, "allow")
        self.assertEqual(report.decisions[0].reason_code, "policy_allowed")


class PolicyValidatorRawControlTests(unittest.TestCase):
    def test_nested_raw_control_identifiers_are_denied(self) -> None:
        registry = _registry_with_stop_parameter("payload", list)
        payloads = (
            [{"motion": {"joint_position": 0.25}}],
            [{"profile": ["velocity_limit=0.25"]}],
            [["torque=3.0"]],
            [{"update": {"name": "firmware_mode"}}],
        )
        for index, payload in enumerate(payloads, start=1):
            with self.subTest(payload=payload):
                action_id = f"act-raw-{index}"
                graph = _graph(_action(ActionType.STOP, action_id=action_id, parameters={"payload": payload}))
                report = _validator(
                    registry=registry,
                    high_impact_actions=frozenset({ActionType.STOP}),
                ).check(graph, confirmed_action_ids=frozenset({action_id}))
                self.assertFalse(report.is_valid)
                self.assertEqual(report.decisions[0].outcome, "deny")
                self.assertEqual(report.decisions[0].reason_code, "raw_control_parameter")
                self.assertTrue(report.decisions[0].findings)

    def test_plain_prose_is_not_misclassified_as_a_raw_parameter(self) -> None:
        registry = _registry_with_stop_parameter("note", str)
        notes = (
            (
                "This explanation mentions joint behavior, velocity profiles, torque margins, "
                "and firmware safety without encoding a control parameter."
            ),
            "Firmware: safety remains outside this policy.",
            "Joint: a mechanical connection, not a command.",
        )
        for note in notes:
            with self.subTest(note=note):
                graph = _graph(_action(ActionType.STOP, parameters={"note": note}))
                report = _validator(registry=registry).check(graph)

                self.assertTrue(report.is_valid, report.decisions)

    def test_disguised_raw_control_identifiers_are_denied(self) -> None:
        registry = _registry_with_stop_parameter("payload", list)
        payloads = (
            [{"joint velocity": 1}],
            [{"firmware/mode": "update"}],
            [{"JOINTVELOCITY": 1}],
            ['{"joint\\u005fvelocity":1}'],
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                report = _validator(registry=registry).check(
                    _graph(_action(ActionType.STOP, parameters={"payload": payload}))
                )

                self.assertFalse(report.is_valid)
                self.assertEqual(report.decisions[0].reason_code, "raw_control_parameter")

    def test_non_string_mapping_key_fails_closed(self) -> None:
        registry = _registry_with_stop_parameter("payload", list)
        payload = [{("torque_limit",): 1}]

        report = _validator(registry=registry).check(_graph(_action(ActionType.STOP, parameters={"payload": payload})))

        self.assertFalse(report.is_valid)
        self.assertEqual(report.decisions[0].reason_code, "policy_input_malformed")

    def test_excessive_payload_nesting_fails_closed_structurally(self) -> None:
        registry = _registry_with_stop_parameter("payload", list)
        payload: object = "safe"
        for _ in range(1200):
            payload = [payload]

        report = _validator(registry=registry).check(_graph(_action(ActionType.STOP, parameters={"payload": payload})))

        self.assertFalse(report.is_valid)
        self.assertEqual(report.decisions[0].reason_code, "policy_input_malformed")
        self.assertTrue(any("scan limit" in finding.message for finding in report.findings))


class PolicyValidatorConfirmationTests(unittest.TestCase):
    def test_high_impact_action_requires_confirmation(self) -> None:
        graph = _graph(
            _action(ActionType.ASK_CONFIRM, parameters={"question": "place it?"}),
            _action(
                ActionType.PLACE,
                action_id="act-place",
                target_id="red_block",
                parameters={"destination_id": "tray"},
            ),
        )

        report = _validator(high_impact_actions=frozenset({ActionType.PLACE})).check(graph)

        self.assertFalse(report.is_valid)
        self.assertEqual(report.decisions[0].outcome, "allow")
        self.assertEqual(report.decisions[1].outcome, "confirmation_required")
        self.assertEqual(report.decisions[1].reason_code, "action_confirmation_required")
        self.assertEqual(report.decisions[1].policy_version, POLICY_VERSION)

    def test_confirmation_is_scoped_to_exact_action_id(self) -> None:
        graph = _graph(
            _action(
                ActionType.PLACE,
                action_id="act-place",
                target_id="red_block",
                parameters={"destination_id": "tray"},
            )
        )
        validator = _validator(high_impact_actions=frozenset({ActionType.PLACE}))

        report = validator.check(graph, confirmed_action_ids=frozenset({"act-other"}))

        self.assertFalse(report.is_valid)
        self.assertEqual(report.decisions[0].action_id, "act-place")
        self.assertEqual(report.decisions[0].outcome, "confirmation_required")

    def test_malformed_confirmation_ids_fail_closed_without_substring_matching(self) -> None:
        graph = _graph(
            _action(
                ActionType.PLACE,
                action_id="act-place",
                target_id="red_block",
                parameters={"destination_id": "tray"},
            )
        )
        validator = _validator(high_impact_actions=frozenset({ActionType.PLACE}))
        malformed_values = (
            "act-place-other",
            ["act-place"],
            frozenset({" "}),
            frozenset({1}),
        )

        for confirmed_action_ids in malformed_values:
            with self.subTest(confirmed_action_ids=confirmed_action_ids):
                report = validator.check(
                    graph,
                    confirmed_action_ids=confirmed_action_ids,  # type: ignore[arg-type]
                )

                self.assertFalse(report.is_valid)
                self.assertEqual(report.decisions[0].outcome, "deny")
                self.assertEqual(report.decisions[0].reason_code, "confirmation_input_malformed")

    def test_matching_confirmation_allows_registry_valid_high_impact_action(self) -> None:
        valid_graph = _graph(
            _action(
                ActionType.PLACE,
                action_id="act-place",
                target_id="red_block",
                parameters={"destination_id": "tray"},
            )
        )
        invalid_graph = _graph(
            _action(ActionType.PLACE, action_id="act-place-invalid", target_id="red_block", parameters={})
        )
        validator = _validator(high_impact_actions=frozenset({ActionType.PLACE}))

        valid_report = validator.check(valid_graph, confirmed_action_ids=frozenset({"act-place"}))
        invalid_report = validator.check(
            invalid_graph,
            confirmed_action_ids=frozenset({"act-place-invalid"}),
        )

        self.assertTrue(valid_report.is_valid, valid_report.decisions)
        self.assertEqual(valid_report.decisions[0].outcome, "allow")
        self.assertEqual(invalid_report.decisions[0].outcome, "deny")
        self.assertEqual(invalid_report.decisions[0].reason_code, "tool_registry_denied")


class PolicyValidatorIssue58EnforcementTests(unittest.TestCase):
    def test_enforce_rejects_deny_and_confirmation_required(self) -> None:
        denied_graph = _graph(_action(ActionType.OBSERVE, action_id="act-denied"))
        confirmation_graph = _graph(
            _action(
                ActionType.PLACE,
                action_id="act-confirm",
                target_id="red_block",
                parameters={"destination_id": "tray"},
            )
        )

        with self.assertRaises(PolicyViolation) as denied:
            _validator(registry=ToolRegistry(load_defaults=False)).enforce(denied_graph)
        with self.assertRaises(PolicyViolation) as confirmation:
            _validator(high_impact_actions=frozenset({ActionType.PLACE})).enforce(confirmation_graph)

        self.assertEqual(denied.exception.report.decisions[0].step_id, "step-1")
        self.assertEqual(denied.exception.report.decisions[0].reason_code, "tool_registry_denied")
        self.assertEqual(confirmation.exception.report.decisions[0].action_id, "act-confirm")
        self.assertEqual(confirmation.exception.report.decisions[0].outcome, "confirmation_required")

    def test_policy_output_is_authorization_only(self) -> None:
        from workbench_contracts import ActionResult, VerificationResult

        report = _validator().check(_graph(_action(ActionType.OBSERVE)))
        decision = report.decisions[0]

        self.assertIsInstance(report, PolicyReport)
        self.assertNotIsInstance(report, (ActionResult, VerificationResult))
        self.assertNotIsInstance(decision, (ActionResult, VerificationResult))
        for forbidden_attribute in (
            "dispatch_state",
            "device_state",
            "evidence_refs",
            "verification_id",
            "completed",
        ):
            self.assertFalse(hasattr(report, forbidden_attribute))
            self.assertFalse(hasattr(decision, forbidden_attribute))


if __name__ == "__main__":
    unittest.main()
