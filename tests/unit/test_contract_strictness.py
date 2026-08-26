import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libs" / "contracts"))

from workbench_contracts import (
    ActionResult,
    ActionType,
    Observation,
    Orientation,
    Pose,
    Position,
    ScenarioManifest,
    SemanticAction,
    TaskGraph,
    TaskStep,
    VerificationResult,
    VerificationStatus,
    WorldEvent,
    WorldEventType,
)

CANONICAL_MODELS = (
    Position,
    Orientation,
    Pose,
    Observation,
    SemanticAction,
    ActionResult,
    WorldEvent,
    TaskStep,
    TaskGraph,
    VerificationResult,
    ScenarioManifest,
)


def valid_pose() -> Pose:
    return Pose(
        frame_id="table",
        position=Position(x=0.2, y=0.1, z=0.02),
        orientation=Orientation(x=0.0, y=0.0, z=0.0, w=1.0),
    )


def valid_observation(**updates: object) -> Observation:
    values: dict[str, object] = {
        "observation_id": "obs-001",
        "run_id": "run-001",
        "entity_id": "red_block",
        "entity_type": "block",
        "pose": valid_pose(),
        "confidence": 0.98,
        "observed_at": "2026-08-25T00:00:00Z",
        "evidence_refs": ["camera-frame-001"],
    }
    return Observation(**(values | updates))


@pytest.mark.parametrize("model", CANONICAL_MODELS, ids=lambda model: model.__name__)
def test_canonical_runtime_models_share_fail_closed_configuration(model: type) -> None:
    assert model.model_config["strict"] is True
    assert model.model_config["extra"] == "forbid"


def test_unknown_fields_are_rejected_at_top_level_and_nested_boundaries() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        SemanticAction(
            action_id="act-001",
            action_type=ActionType.OBSERVE,
            unexpected=True,
        )

    payload = json.loads((ROOT / "interfaces" / "examples" / "observation-red-block.json").read_text())
    payload["pose"]["position"]["unexpected"] = 0
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Observation.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "operation",
    [
        lambda: Position.model_validate({"x": "1", "y": 2.0, "z": 3.0}),
        lambda: Position.model_validate_json('{"x":"1","y":2.0,"z":3.0}'),
        lambda: WorldEvent(
            event_id="evt-001",
            run_id="run-001",
            sequence_no=True,
            event_type=WorldEventType.OBSERVATION,
            occurred_at="2026-08-25T00:00:00Z",
        ),
        lambda: ScenarioManifest(
            scenario_id="scenario-001",
            seed=True,
            task_id="task-001",
            world_version="v1",
            timeout_s=120,
        ),
        lambda: SemanticAction.model_validate({"action_id": "act-001", "action_type": "observe"}),
    ],
    ids=["python-number-string", "json-number-string", "bool-as-sequence", "bool-as-seed", "python-enum-string"],
)
def test_implicit_python_and_json_coercion_is_rejected(operation) -> None:
    with pytest.raises(ValidationError):
        operation()


def test_schema_declared_empty_collections_are_rejected() -> None:
    with pytest.raises(ValidationError, match="steps"):
        TaskGraph(task_id="task-empty", goal="test", steps=[], planner="test")

    with pytest.raises(ValidationError, match="evidence_refs"):
        valid_observation(evidence_refs=[])

    with pytest.raises(ValidationError, match="evidence_refs"):
        VerificationResult(
            verification_id="verification-001",
            run_id="run-001",
            task_id="task-001",
            claim="insufficient evidence",
            status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            evidence_refs=[],
            verified_at="2026-08-25T00:00:00Z",
        )


def test_observation_hamming_matches_schema_minimum() -> None:
    with pytest.raises(ValidationError, match="hamming"):
        valid_observation(hamming=-1)

    repository_schema = json.loads(
        (ROOT / "interfaces" / "json_schema" / "observation.schema.json").read_text(encoding="utf-8")
    )
    model_schema = Observation.model_json_schema()
    integer_branch = next(
        branch for branch in model_schema["properties"]["hamming"]["anyOf"] if branch.get("type") == "integer"
    )
    assert integer_branch["minimum"] == repository_schema["properties"]["hamming"]["minimum"] == 0


def test_task_graph_steps_matches_schema_minimum() -> None:
    repository_schema = json.loads(
        (ROOT / "interfaces" / "json_schema" / "task_graph.schema.json").read_text(encoding="utf-8")
    )
    model_schema = TaskGraph.model_json_schema()
    assert model_schema["properties"]["steps"]["minItems"] == repository_schema["properties"]["steps"]["minItems"]


@pytest.mark.parametrize(
    ("example_name", "model"),
    [
        ("action-result-place-confirmed.json", ActionResult),
        ("observation-red-block.json", Observation),
        ("scenario-normal-001.json", ScenarioManifest),
        ("semantic-action-place.json", SemanticAction),
        ("verification-insufficient-evidence.json", VerificationResult),
    ],
)
def test_valid_repository_examples_round_trip_deterministically(example_name: str, model: type) -> None:
    payload = (ROOT / "interfaces" / "examples" / example_name).read_text(encoding="utf-8")

    value = model.model_validate_json(payload)
    first = value.model_dump_json()
    second = value.model_dump_json()

    assert first == second
    assert model.model_validate_json(first) == value


def test_valid_world_event_and_task_graph_json_round_trip() -> None:
    world_event_json = json.dumps(
        {
            "event_id": "evt-001",
            "run_id": "run-001",
            "sequence_no": 0,
            "event_type": "observation",
            "occurred_at": "2026-08-25T00:00:00Z",
            "payload": {},
        }
    )
    task_graph_json = json.dumps(
        {
            "task_id": "task-001",
            "goal": "observe the workbench",
            "steps": [
                {
                    "step_id": "step-001",
                    "action": {"action_id": "act-001", "action_type": "observe"},
                }
            ],
            "planner": "template-v1",
        }
    )

    for model, payload in ((WorldEvent, world_event_json), (TaskGraph, task_graph_json)):
        value = model.model_validate_json(payload)
        serialized = value.model_dump_json()
        assert model.model_validate_json(serialized) == value
