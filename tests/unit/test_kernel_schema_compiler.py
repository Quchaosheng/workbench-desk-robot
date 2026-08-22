import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libs" / "kernel"))

from workbench.kernel.schema_compiler import SchemaCompiler, SchemaValidationError, validate_schema_instance


def test_runtime_number_validation_handles_large_integers_and_non_finite_floats() -> None:
    for value in (10**400, 1, 1.5):
        validate_schema_instance(value, {"type": "number"})

    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(SchemaValidationError, match="finite"):
            validate_schema_instance(value, {"type": "number"})


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "number", "minimum": "not-a-number"},
        {"type": "number", "maximum": "not-a-number"},
        {"type": "number", "maximum": float("inf")},
        {"type": "string", "pattern": "["},
        {"type": "string", "pattern": 123},
        {"type": "array", "minItems": "not-an-integer"},
    ],
)
def test_runtime_validation_normalizes_malformed_constraints(schema: dict) -> None:
    value = 1 if schema.get("type") == "number" else "value" if schema.get("type") == "string" else []
    with pytest.raises(SchemaValidationError):
        validate_schema_instance(value, schema)


def test_generated_models_are_valid_and_typed(tmp_path: Path) -> None:
    compiler = SchemaCompiler(ROOT / "interfaces" / "json_schema")
    compiler.load_schemas()

    python_dir = tmp_path / "python"
    typescript_dir = tmp_path / "typescript"
    compiler.compile_all(python_dir, typescript_dir)

    generated = python_dir / "action_result.py"
    namespace = {}
    exec(compile(generated.read_text(encoding="utf-8"), str(generated), "exec"), namespace)
    model = namespace["ActionResult"]
    assert issubclass(model, BaseModel)
    assert model.model_fields["action_id"].is_required()
    assert not model.model_fields["error_code"].is_required()

    typescript = (typescript_dir / "action_result.ts").read_text(encoding="utf-8")
    assert "export interface ActionResult {" in typescript
    assert '"action_id": string;' in typescript
    assert '"error_code"?: number | null;' in typescript
    assert all(compiler.verify_type_compatibility().values())


def generated_model(tmp_path: Path, schema_name: str, model_name: str):
    compiler = SchemaCompiler(ROOT / "interfaces" / "json_schema")
    compiler.load_schemas()
    python_dir = tmp_path / "python"
    compiler.compile_all(python_dir, tmp_path / "typescript")
    generated = python_dir / f"{schema_name}.py"
    namespace = {}
    exec(compile(generated.read_text(encoding="utf-8"), str(generated), "exec"), namespace)
    return namespace[model_name]


def test_generated_models_enforce_repository_constraints(tmp_path: Path) -> None:
    world_event = generated_model(tmp_path, "world_event", "WorldEvent")
    with pytest.raises(ValueError):
        world_event(event_id="e", run_id="r", sequence_no=-1, event_type="fault", occurred_at="t", payload={})

    task_graph = generated_model(tmp_path, "task_graph", "TaskGraph")
    with pytest.raises(ValueError):
        task_graph(task_id="t", goal="g", steps=[], planner="p", model_route="template")

    world_state = generated_model(tmp_path, "world_state", "WorldState")
    with pytest.raises(ValueError):
        world_state(run_id="r", sequence_no=0, state_hash="short", entities=[], reduced_at="t")
    with pytest.raises(ValueError):
        world_state(
            run_id="r",
            sequence_no=0,
            state_hash="0" * 64,
            entities=[{"entity_id": "x", "entity_type": "block", "belief": "observed", "confidence": 2.0}],
            reduced_at="t",
        )


def test_generated_models_validate_local_references(tmp_path: Path) -> None:
    observation = generated_model(tmp_path, "observation", "Observation")
    valid = {
        "observation_id": "o",
        "run_id": "r",
        "entity_id": "x",
        "entity_type": "block",
        "pose": {
            "frame_id": "world",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        },
        "confidence": 0.9,
        "observed_at": "t",
        "source": "camera-1",
        "evidence_refs": ["frame://1"],
    }
    assert observation(**valid)
    valid["pose"]["position"]["x"] = "not-a-number"
    with pytest.raises(ValueError):
        observation(**valid)


def test_generated_mcu_model_enforces_protocol_branches(tmp_path: Path) -> None:
    mcu_frame = generated_model(tmp_path, "mcu_protocol", "McuFrame")
    schema = json.loads((ROOT / "interfaces/json_schema/mcu_protocol.schema.json").read_text(encoding="utf-8"))
    valid = json.loads((ROOT / "interfaces/examples/mcu-frame-stop-ack.json").read_text(encoding="utf-8"))
    invalid = []
    for field in ("protocol_version", "opcode", "sent_at_us"):
        payload = deepcopy(valid)
        payload.pop(field)
        invalid.append(payload)
    for updates in (
        {"sent_at": "legacy"},
        {"sequence_no": None},
        {"opcode": "hold"},
        {"result_code": 0, "fault_code": "stop_rejected", "device_mode": "faulted"},
        {"result_code": 1, "fault_code": "none", "device_mode": "stopped"},
    ):
        payload = {**valid, **updates}
        invalid.append(payload)

    frame = mcu_frame.model_validate(valid)
    serialized = frame.model_dump(mode="json")
    assert serialized == valid
    assert mcu_frame.model_validate(serialized) == frame
    for payload in invalid:
        assert list(Draft202012Validator(schema).iter_errors(payload))
        with pytest.raises(ValueError):
            mcu_frame.model_validate(payload)


def test_generated_mcu_model_rejects_unknown_branch_keywords(tmp_path: Path) -> None:
    compiler = SchemaCompiler(ROOT / "interfaces" / "json_schema")
    compiler.load_schemas()
    compiler.schemas["mcu_protocol"]["allOf"][0]["then"]["dependentRequired"] = {"opcode": ["command_id"]}

    with pytest.raises(ValueError, match=r"unsupported runtime schema keyword.*dependentRequired"):
        compiler.compile_all(tmp_path / "python", tmp_path / "typescript")


def test_explicit_extra_forbid_and_unsupported_keywords_fail_closed(tmp_path: Path) -> None:
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir()
    (schema_dir / "strict.schema.json").write_text(
        '{"title":"Strict","type":"object","additionalProperties":false,"properties":{"id":{"type":"string"}}}',
        encoding="utf-8",
    )
    compiler = SchemaCompiler(schema_dir)
    compiler.load_schemas()
    python_dir = tmp_path / "strict-python"
    compiler.compile_all(python_dir, tmp_path / "strict-typescript")
    namespace = {}
    generated = python_dir / "strict.py"
    exec(compile(generated.read_text(encoding="utf-8"), str(generated), "exec"), namespace)
    with pytest.raises(ValueError):
        namespace["Strict"](id="x", unexpected=True)

    (schema_dir / "unsupported.schema.json").write_text(
        '{"title":"Unsupported","type":"object","properties":{"id":{"type":"string","format":"uuid"}}}',
        encoding="utf-8",
    )
    compiler.load_schemas()
    with pytest.raises(ValueError, match=r"unsupported.*format"):
        compiler.compile_all(tmp_path / "bad-python", tmp_path / "bad-typescript")
