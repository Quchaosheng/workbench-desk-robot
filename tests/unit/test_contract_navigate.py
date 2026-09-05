from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "libs/contracts"),
    str(ROOT / "services/agent_runtime"),
]

from workbench_agent_runtime.policy_validator import PolicyValidator
from workbench_agent_runtime.tool_registry import ToolRegistry
from workbench_contracts import (
    ActionOutcome,
    ActionResult,
    ActionType,
    DeviceState,
    DispatchState,
    SemanticAction,
    TaskGraph,
    TaskStep,
)

SCHEMA = json.loads((ROOT / "interfaces/json_schema/semantic_action.schema.json").read_text(encoding="utf-8"))


def navigate_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "action_id": "act-navigate-home",
        "action_type": "navigate",
        "target_id": "workbench_home",
        "parameters": {},
    }
    payload.update(updates)
    return payload


def navigate_action(**updates: object) -> SemanticAction:
    payload = navigate_payload(**updates)
    return SemanticAction(
        action_id=payload["action_id"],
        action_type=ActionType.NAVIGATE,
        target_id=payload.get("target_id"),
        parameters=payload.get("parameters", {}),
    )


def action_graph(action: SemanticAction) -> TaskGraph:
    return TaskGraph(
        task_id="task-navigate",
        goal="navigate to the configured waypoint",
        steps=[TaskStep(step_id="navigate", action=action)],
        planner="test",
        model_route="template",
    )


def test_navigate_example_is_valid_against_schema_and_model() -> None:
    example_path = ROOT / "interfaces/examples/semantic-action-navigate.json"
    raw = example_path.read_text(encoding="utf-8")
    payload = json.loads(raw)

    assert list(Draft202012Validator(SCHEMA).iter_errors(payload)) == []

    action = SemanticAction.model_validate_json(raw)

    assert action.action_type is ActionType.NAVIGATE
    assert action.target_id == "workbench_home"
    assert action.parameters == {}
    assert SemanticAction.model_validate_json(action.model_dump_json()) == action


def test_generated_model_schema_exposes_the_same_navigate_boundary() -> None:
    generated_schema = SemanticAction.model_json_schema()

    assert list(Draft202012Validator(generated_schema).iter_errors(navigate_payload())) == []
    assert list(
        Draft202012Validator(generated_schema).iter_errors(
            navigate_payload(parameters={"pose": {"x": 1.0, "y": 2.0, "z": 0.0}})
        )
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"target_id": None},
        {"target_id": ""},
        {"target_id": "   "},
        {"parameters": {"waypoint": "other"}},
        {"parameters": {"x": 1.0, "y": 2.0}},
        {"parameters": {"velocity": 0.1}},
    ],
    ids=["missing-target", "empty-target", "blank-target", "selector", "coordinates", "velocity"],
)
def test_pydantic_rejects_invalid_navigate_boundary(updates: dict[str, object]) -> None:
    payload = navigate_payload(**updates)

    with pytest.raises(ValidationError):
        SemanticAction.model_validate(payload)

    with pytest.raises(ValidationError):
        SemanticAction.model_validate_json(json.dumps(payload))


def test_pydantic_rejects_unknown_top_level_navigate_fields() -> None:
    payload = navigate_payload(unexpected="value")

    with pytest.raises(ValidationError, match="extra_forbidden"):
        SemanticAction.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        navigate_payload(target_id=None),
        navigate_payload(target_id=""),
        navigate_payload(target_id="   "),
        navigate_payload(parameters={"pose": {"frame_id": "map"}}),
        navigate_payload(parameters={"speed_profile": "slow"}),
        navigate_payload(unexpected="value"),
    ],
    ids=["missing-target", "empty-target", "blank-target", "pose", "free-selector", "extra-field"],
)
def test_json_schema_rejects_invalid_navigate_boundary(payload: dict[str, object]) -> None:
    assert list(Draft202012Validator(SCHEMA).iter_errors(payload))


def test_legacy_place_example_remains_compatible() -> None:
    example_path = ROOT / "interfaces/examples/semantic-action-place.json"
    raw = example_path.read_text(encoding="utf-8")
    payload = json.loads(raw)

    assert list(Draft202012Validator(SCHEMA).iter_errors(payload)) == []
    assert SemanticAction.model_validate_json(raw).action_type is ActionType.PLACE


def test_registry_and_policy_consume_navigate_from_the_single_allow_list() -> None:
    action = navigate_action()
    registry = ToolRegistry()

    result = registry.validate(action)
    report = PolicyValidator(
        registry=registry,
        policy_config={"policy_version": "navigate-policy-v1", "high_impact_actions": frozenset()},
    ).check(action_graph(action))

    assert result.is_valid, result.errors
    assert ActionType.NAVIGATE in registry.list_all()
    assert report.is_valid
    assert report.decisions[0].reason_code.value == "policy_allowed"


def test_policy_can_require_confirmation_for_navigate_without_affecting_stop() -> None:
    action = navigate_action(action_id="act-navigate-confirmed")
    validator = PolicyValidator(
        policy_config={
            "policy_version": "navigate-policy-v1",
            "high_impact_actions": frozenset({ActionType.NAVIGATE}),
        }
    )

    required = validator.check(action_graph(action))
    confirmed = validator.check(
        action_graph(action),
        confirmed_action_ids=frozenset({action.action_id}),
    )

    assert not required.is_valid
    assert required.decisions[0].reason_code.value == "action_confirmation_required"
    assert confirmed.is_valid


@pytest.mark.parametrize(
    "updates",
    [
        {"target_id": None},
        {"target_id": "   "},
    ],
    ids=["missing-target", "blank-target"],
)
def test_registry_rejects_malformed_navigate_constructed_at_a_lower_boundary(updates: dict[str, object]) -> None:
    payload = navigate_payload(**updates)
    malformed = SemanticAction.model_construct(
        action_id=payload["action_id"],
        action_type=ActionType.NAVIGATE,
        target_id=payload["target_id"],
        parameters={},
    )

    result = ToolRegistry().validate(malformed)

    assert not result.is_valid
    assert any(error.field == "target_id" for error in result.errors)


def test_registry_rejects_raw_navigation_payload_even_if_model_validation_was_bypassed() -> None:
    malformed = SemanticAction.model_construct(
        action_id="act-navigate-raw",
        action_type=ActionType.NAVIGATE,
        target_id="workbench_home",
        parameters={"map": "map.yaml", "x": 1.0, "y": 2.0},
    )

    result = ToolRegistry().validate(malformed)

    assert not result.is_valid
    assert any("forbidden keys" in error.message for error in result.errors)


def test_stop_remains_a_separate_registered_action() -> None:
    registry = ToolRegistry()

    stop = SemanticAction(action_id="act-stop", action_type=ActionType.STOP)

    assert ActionType.STOP in registry.list_all()
    assert registry.validate(stop).is_valid


def test_completed_navigation_result_has_no_observation_or_verification_claim() -> None:
    result = ActionResult(
        result_id="result-navigate-home",
        action_id="act-navigate-home",
        run_id="run-navigate",
        outcome=ActionOutcome.COMPLETED,
        dispatch_state=DispatchState.SENT,
        device_state=DeviceState.CONFIRMED,
        started_at="2026-09-03T00:00:00Z",
        ended_at="2026-09-03T00:00:01Z",
    )

    assert result.entity_id is None
    assert result.resulting_location is None
    assert result.outcome is ActionOutcome.COMPLETED
