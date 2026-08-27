"""Validate every committed contract example against its schema and typed model.

Independent checks run here:
1. Every schema is registered (no schema without an example or a stated reason)
2. All example files parse as valid JSON
3. All required fields in schemas are also defined in properties
4. All examples satisfy the required fields of their schema
5. jsonschema Draft-2020-12 full structural validation (enum, type, allOf, $ref, etc.)
6. Pydantic models accept their examples (runtime type check)
7. Pydantic output satisfies the source schema and rejects omitted schema-required fields
8. Template planner round-trips to JSON

The jsonschema check (5) is what was missing before — it catches enum mismatches,
type errors, range violations and $ref constraints that a manual field-presence check
silently ignores.
"""

import json
import sys
from dataclasses import dataclass
from typing import Any

from _paths import ROOT, enable_local_packages

enable_local_packages()

from workbench_agent_runtime import build_template_plan
from workbench_contracts import (
    ActionResult,
    EmotionIntent,
    McuFrame,
    Observation,
    Pose,
    ScenarioManifest,
    SemanticAction,
    TaskGraph,
    VerificationResult,
    WorldEvent,
    WorldState,
)

try:
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

SCHEMA_DIR = ROOT / "interfaces" / "json_schema"
EXAMPLE_DIR = ROOT / "interfaces" / "examples"


@dataclass(frozen=True)
class SchemaCoverage:
    """Executable ownership record for one committed JSON Schema."""

    stem: str
    example: str | None
    model: type[Any] | None
    schema_only_fields: frozenset[str] = frozenset()
    exemption_owner: str | None = None
    exemption_reason: str | None = None
    replacement_validation: str | None = None


# Every schema MUST have one entry. A missing example/model is allowed only when
# all three exemption fields are populated; this keeps a reviewed escape hatch
# without allowing an untracked None entry to silently reduce coverage.
SCHEMA_COVERAGE = (
    SchemaCoverage("action_result", "action-result-place-confirmed.json", ActionResult),
    SchemaCoverage("emotion_intent", "emotion-intent-uncertain.json", EmotionIntent),
    SchemaCoverage(
        "mcu_protocol",
        "mcu-frame-stop-ack.json",
        McuFrame,
        schema_only_fields=frozenset({"sent_at"}),
        exemption_owner="TH3478",
        exemption_reason="Legacy Schema Compiler field rejected by every MCU Wire V1 frame branch.",
        replacement_validation="tests/unit/test_mcu_protocol_contract.py invalid-frame corpus",
    ),
    SchemaCoverage("observation", "observation-red-block.json", Observation),
    SchemaCoverage("pose", "pose-tabletop.json", Pose),
    SchemaCoverage("scenario", "scenario-normal-001.json", ScenarioManifest),
    SchemaCoverage("semantic_action", "semantic-action-place.json", SemanticAction),
    SchemaCoverage("task_graph", "task-graph-place.json", TaskGraph),
    SchemaCoverage("verification_result", "verification-insufficient-evidence.json", VerificationResult),
    SchemaCoverage("world_event", "world-event-observation.json", WorldEvent),
    SchemaCoverage("world_state", "world-state-block-in-tray.json", WorldState),
)


def check_every_schema_is_registered() -> list[str]:
    on_disk = {p.name.removesuffix(".schema.json") for p in SCHEMA_DIR.glob("*.schema.json")}
    entries_by_stem: dict[str, list[SchemaCoverage]] = {}
    for entry in SCHEMA_COVERAGE:
        entries_by_stem.setdefault(entry.stem, []).append(entry)
    problems = []
    for stem in sorted(on_disk):
        entries = entries_by_stem.get(stem, [])
        if not entries:
            problems.append(f"{stem}.schema.json has no coverage entry")
            continue
        if len(entries) != 1:
            problems.append(f"{stem}.schema.json has {len(entries)} coverage entries; exactly one is required")
            continue
        entry = entries[0]
        has_model = entry.model is not None
        has_example = entry.example is not None
        has_exemption = all(
            isinstance(value, str) and bool(value.strip())
            for value in (entry.exemption_owner, entry.exemption_reason, entry.replacement_validation)
        )
        if not (has_model and has_example) and not has_exemption:
            problems.append(
                f"{stem}.schema.json needs a typed model and example, or an owner/reason/replacement exemption"
            )
        if entry.schema_only_fields and not has_exemption:
            problems.append(f"{stem}.schema.json schema-only fields need owner/reason/replacement metadata")
    for stem in sorted(set(entries_by_stem) - on_disk):
        problems.append(f"{stem} has a coverage entry but no committed schema")
    return problems


def check_schema_properties_have_model_fields() -> list[str]:
    """Catch declared schema fields that a mapped object model would reject."""
    problems = []
    for entry in sorted(SCHEMA_COVERAGE, key=lambda item: item.stem):
        if entry.model is None:
            continue
        schema_path = SCHEMA_DIR / f"{entry.stem}.schema.json"
        if not schema_path.is_file():
            continue
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        model_schema = entry.model.model_json_schema()
        model_fields = set(model_schema.get("properties", {}))
        if not model_fields:
            for definition in model_schema.get("$defs", {}).values():
                model_fields.update(definition.get("properties", {}))
        missing = set(schema.get("properties", {})) - model_fields
        for field_name in sorted(missing - entry.schema_only_fields):
            problems.append(f"{entry.stem}.schema.json field {field_name!r} has no mapped Pydantic field")
        for field_name in sorted(entry.schema_only_fields - missing):
            problems.append(
                f"{entry.stem}.schema.json field {field_name!r} is marked schema-only but has a Pydantic field"
            )
        if model_schema.get("properties") is not None:
            schema_required = set(schema.get("required", []))
            model_required = set(model_schema.get("required", []))
            for field_name in sorted(schema_required - model_required):
                problems.append(f"{entry.stem}.schema.json field {field_name!r} is required but optional in Pydantic")
            for field_name in sorted(model_required - schema_required):
                problems.append(f"{entry.model.__name__} requires schema-optional field {field_name!r}")
    return problems


def check_examples_parse() -> list[str]:
    problems = []
    for path in sorted(EXAMPLE_DIR.glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{path.name} is not valid JSON: {exc}")
    return problems


def check_required_fields_are_defined() -> list[str]:
    """A schema that requires a field it never defines will silently accept a
    document missing that field. This check exists because two schemas shipped
    with exactly that defect."""
    problems = []
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        defined = set(schema.get("properties", {}))
        for field in schema.get("required", []):
            if field not in defined:
                problems.append(f"{path.name} requires '{field}' but never defines it")
    return problems


def check_examples_satisfy_required() -> list[str]:
    problems = []
    for entry in sorted(SCHEMA_COVERAGE, key=lambda item: item.stem):
        stem, example_name = entry.stem, entry.example
        if example_name is None:
            continue
        example_path = EXAMPLE_DIR / example_name
        if not example_path.is_file():
            problems.append(f"{stem}: example {example_name} is missing")
            continue
        schema = json.loads((SCHEMA_DIR / f"{stem}.schema.json").read_text(encoding="utf-8"))
        example = json.loads(example_path.read_text(encoding="utf-8"))
        for field in schema.get("required", []):
            if field not in example:
                problems.append(f"{example_name} is missing required field '{field}'")
    return problems


def _schema_registry() -> "Registry":
    """Register every schema under its bare filename so a sibling $ref such as
    {"$ref": "pose.schema.json"} resolves without a network fetch."""
    resources = []
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        contents = json.loads(path.read_text(encoding="utf-8"))
        resources.append((path.name, Resource.from_contents(contents)))
    return Registry().with_resources(resources)


def check_jsonschema_validation() -> list[str]:
    """Full Draft-2020-12 structural validation: enum, type, range, allOf, $ref.
    This is what the previous version was missing — the checks above only verify
    field presence, not field values.
    """
    if not HAS_JSONSCHEMA:
        return [
            "jsonschema is not installed; run `pip install jsonschema` to enable "
            "full structural validation. Install it by adding 'jsonschema>=4,<5' to "
            "[project.optional-dependencies].dev in pyproject.toml."
        ]

    problems = []
    for entry in sorted(SCHEMA_COVERAGE, key=lambda item: item.stem):
        stem, example_name = entry.stem, entry.example
        if example_name is None:
            continue
        schema_path = SCHEMA_DIR / f"{stem}.schema.json"
        example_path = EXAMPLE_DIR / example_name
        if not example_path.is_file():
            continue  # already reported by check_examples_satisfy_required

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        example = json.loads(example_path.read_text(encoding="utf-8"))

        validator = Draft202012Validator(schema, registry=_schema_registry())

        errors = list(validator.iter_errors(example))
        for err in errors:
            path = " -> ".join(str(p) for p in err.absolute_path) or "(root)"
            problems.append(f"{example_name} [{path}]: {err.message}")
    return problems


def check_models_accept_examples() -> list[str]:
    problems = []
    for entry in sorted(SCHEMA_COVERAGE, key=lambda item: item.stem):
        example_name, model = entry.example, entry.model
        if example_name is None or model is None:
            continue
        path = EXAMPLE_DIR / example_name
        if not path.is_file():
            problems.append(f"{example_name}: file missing, cannot validate {model.__name__}")
            continue
        try:
            model.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{model.__name__} rejected {example_name}: {exc}")
    return problems


def check_bidirectional_model_validation() -> list[str]:
    """Validate both the committed JSON input and canonical model output."""
    if not HAS_JSONSCHEMA:
        return ["jsonschema is not installed; bidirectional contract validation is unavailable"]

    problems = []
    registry = _schema_registry()
    for entry in sorted(SCHEMA_COVERAGE, key=lambda item: item.stem):
        if entry.example is None or entry.model is None:
            continue
        example_path = EXAMPLE_DIR / entry.example
        schema_path = SCHEMA_DIR / f"{entry.stem}.schema.json"
        if not example_path.is_file() or not schema_path.is_file():
            continue
        try:
            raw = example_path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            value = entry.model.model_validate_json(raw)
            serialized = value.model_dump(mode="json")
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            validator = Draft202012Validator(schema, registry=registry)
            errors = list(validator.iter_errors(serialized))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{entry.stem}: model-to-schema validation failed: {exc}")
            continue
        for error in errors:
            path = " -> ".join(str(item) for item in error.absolute_path) or "(root)"
            problems.append(f"{entry.example} serialized [{path}]: {error.message}")

        for field_name in schema.get("required", []):
            if field_name not in payload:
                continue
            without_required = dict(payload)
            del without_required[field_name]
            if not list(validator.iter_errors(without_required)):
                problems.append(f"{entry.stem}.schema.json declares {field_name!r} required but accepts it missing")
                continue
            try:
                entry.model.model_validate_json(json.dumps(without_required))
            except Exception:  # noqa: BLE001
                continue
            problems.append(
                f"{entry.model.__name__} accepts {entry.example} without schema-required field {field_name!r}"
            )

        for field_name in sorted(set(schema.get("properties", {})) - set(schema.get("required", []))):
            if field_name not in payload:
                continue
            without_optional = dict(payload)
            del without_optional[field_name]
            if list(validator.iter_errors(without_optional)):
                continue
            try:
                optional_value = entry.model.model_validate_json(json.dumps(without_optional))
                optional_serialized = optional_value.model_dump(mode="json")
                optional_errors = list(validator.iter_errors(optional_serialized))
            except Exception as exc:  # noqa: BLE001
                problems.append(
                    f"{entry.model.__name__} rejected {entry.example} without schema-optional "
                    f"field {field_name!r}: {exc}"
                )
                continue
            for error in optional_errors:
                path = " -> ".join(str(item) for item in error.absolute_path) or "(root)"
                problems.append(f"{entry.example} without optional {field_name!r} serialized [{path}]: {error.message}")
    return problems


def check_planner_round_trips() -> list[str]:
    try:
        plan = build_template_plan("Place the red block in the tray")
        json.loads(plan.model_dump_json())
    except Exception as exc:  # noqa: BLE001
        return [f"template planner did not produce a serialisable TaskGraph: {exc}"]
    return []


def main() -> int:
    checks = [
        ("every schema registered", check_every_schema_is_registered),
        ("schema properties map to Pydantic fields", check_schema_properties_have_model_fields),
        ("examples parse as JSON", check_examples_parse),
        ("required fields are defined", check_required_fields_are_defined),
        ("examples satisfy required fields", check_examples_satisfy_required),
        ("jsonschema Draft-2020-12 validation", check_jsonschema_validation),
        ("Pydantic models accept examples", check_models_accept_examples),
        ("Pydantic JSON serialization satisfies schemas", check_bidirectional_model_validation),
        ("template planner round-trips", check_planner_round_trips),
    ]
    failed = False
    for label, check in checks:
        problems = check()
        if problems:
            failed = True
            print(f"FAIL  {label}")
            for problem in problems:
                print(f"        {problem}")
        else:
            print(f"ok    {label}")
    if failed:
        print("\ncontract validation failed", file=sys.stderr)
        return 1
    print("\ncontract validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
