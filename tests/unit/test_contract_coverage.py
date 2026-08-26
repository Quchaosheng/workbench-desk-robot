import importlib.util
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from workbench_contracts import WorldEventType

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "tools" / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("validate_contracts", SCRIPTS / "validate_contracts.py")
assert SPEC and SPEC.loader
validate_contracts = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validate_contracts
SPEC.loader.exec_module(validate_contracts)


def test_every_schema_has_one_typed_coverage_entry() -> None:
    assert validate_contracts.check_every_schema_is_registered() == []
    assert validate_contracts.check_schema_properties_have_model_fields() == []
    assert len(validate_contracts.SCHEMA_COVERAGE) == len(list(validate_contracts.SCHEMA_DIR.glob("*.schema.json")))
    assert all(entry.example is not None and entry.model is not None for entry in validate_contracts.SCHEMA_COVERAGE)


def test_each_fixture_round_trips_from_schema_to_model_and_back() -> None:
    assert validate_contracts.check_jsonschema_validation() == []
    assert validate_contracts.check_models_accept_examples() == []
    assert validate_contracts.check_bidirectional_model_validation() == []


def test_unregistered_schema_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    schema_dir = tmp_path / "json_schema"
    schema_dir.mkdir()
    for entry in validate_contracts.SCHEMA_COVERAGE:
        (schema_dir / f"{entry.stem}.schema.json").write_text("{}", encoding="utf-8")
    (schema_dir / "new_runtime_contract.schema.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(validate_contracts, "SCHEMA_DIR", schema_dir)

    problems = validate_contracts.check_every_schema_is_registered()

    assert problems == ["new_runtime_contract.schema.json has no coverage entry"]


def test_complete_reviewed_exemption_is_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    schema_dir = tmp_path / "json_schema"
    schema_dir.mkdir()
    (schema_dir / "reviewed_exemption.schema.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(validate_contracts, "SCHEMA_DIR", schema_dir)
    monkeypatch.setattr(
        validate_contracts,
        "SCHEMA_COVERAGE",
        (
            validate_contracts.SchemaCoverage(
                "reviewed_exemption",
                None,
                None,
                exemption_owner="owner",
                exemption_reason="embedded-only contract",
                replacement_validation="consumer-specific test",
            ),
        ),
    )

    assert validate_contracts.check_every_schema_is_registered() == []


@pytest.mark.parametrize("replacement_validation", [None, "", "   "])
def test_partial_exemption_metadata_fails_closed(
    replacement_validation: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema_dir = tmp_path / "json_schema"
    schema_dir.mkdir()
    (schema_dir / "unreviewed_exemption.schema.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(validate_contracts, "SCHEMA_DIR", schema_dir)
    monkeypatch.setattr(
        validate_contracts,
        "SCHEMA_COVERAGE",
        (
            validate_contracts.SchemaCoverage(
                "unreviewed_exemption",
                None,
                None,
                exemption_owner="owner",
                exemption_reason="missing replacement validation",
                replacement_validation=replacement_validation,
            ),
        ),
    )

    assert validate_contracts.check_every_schema_is_registered() == [
        "unreviewed_exemption.schema.json needs a typed model and example, or an owner/reason/replacement exemption"
    ]


def test_world_event_model_vocabulary_matches_schema() -> None:
    schema = json.loads((ROOT / "interfaces/json_schema/world_event.schema.json").read_text(encoding="utf-8"))
    expected = schema["properties"]["event_type"]["enum"]
    actual = [event_type.value for event_type in WorldEventType]

    assert actual == expected


def test_world_event_optional_schema_fields_round_trip_and_reject_null() -> None:
    payload = {
        "event_id": "evt-001",
        "run_id": "run-001",
        "sequence_no": 0,
        "event_type": "fault",
        "occurred_at": "2026-08-26T00:00:00Z",
        "payload": {},
        "recorded_at": "2026-08-26T00:00:01Z",
        "clock_id": "monotonic",
    }

    value = validate_contracts.WorldEvent.model_validate_json(json.dumps(payload))
    assert value.model_dump(mode="json") == payload | {"evidence_refs": []}

    for field_name in ("recorded_at", "clock_id"):
        invalid = payload | {field_name: None}
        with pytest.raises(ValueError, match="must be omitted instead of null"):
            validate_contracts.WorldEvent.model_validate_json(json.dumps(invalid))


def test_public_world_state_example_is_valid_against_schema_and_model() -> None:
    example_path = ROOT / "interfaces/examples/world-state-block-in-tray.json"
    example = json.loads(example_path.read_text(encoding="utf-8"))
    resources = []
    for path in sorted((ROOT / "interfaces/json_schema").glob("*.schema.json")):
        resources.append((path.name, Resource.from_contents(json.loads(path.read_text(encoding="utf-8")))))
    registry = Registry().with_resources(resources)
    schema = json.loads((ROOT / "interfaces/json_schema/world_state.schema.json").read_text(encoding="utf-8"))

    assert list(Draft202012Validator(schema, registry=registry).iter_errors(example)) == []
    model = validate_contracts.WorldState.model_validate_json(example_path.read_text(encoding="utf-8"))
    assert model.model_dump(mode="json") == example


def test_sparse_world_state_omits_non_nullable_optional_entity_fields() -> None:
    payload = {
        "run_id": "run-001",
        "sequence_no": 0,
        "state_hash": "0" * 64,
        "entities": [
            {
                "entity_id": "red_block",
                "entity_type": "block",
                "belief": "lost",
            }
        ],
        "reduced_at": "2026-08-26T00:00:00Z",
    }

    model = validate_contracts.WorldState.model_validate_json(json.dumps(payload))
    serialized = model.model_dump(mode="json")
    entity = serialized["entities"][0]

    assert "pose" not in entity
    assert "confidence" not in entity
    assert validate_contracts.check_bidirectional_model_validation() == []

    for field_name in ("pose", "confidence"):
        invalid = json.loads(json.dumps(payload))
        invalid["entities"][0][field_name] = None
        with pytest.raises(ValueError, match="must be omitted instead of null"):
            validate_contracts.WorldState.model_validate_json(json.dumps(invalid))
