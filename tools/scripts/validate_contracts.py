"""Validate every committed contract example against its schema and typed model.

Six independent checks run here:
1. Every schema is registered (no schema without an example or a stated reason)
2. All example files parse as valid JSON
3. All required fields in schemas are also defined in properties
4. All examples satisfy the required fields of their schema
5. jsonschema Draft-2020-12 full structural validation (enum, type, allOf, $ref, etc.)
6. Pydantic models accept their examples (runtime type check)
7. Template planner round-trips to JSON

The jsonschema check (5) is what was missing before — it catches enum mismatches,
type errors, range violations and $ref constraints that a manual field-presence check
silently ignores.
"""

import json
import sys

from _paths import ROOT, enable_local_packages

enable_local_packages()

from workbench_agent_runtime import build_template_plan
from workbench_contracts import (
    ActionResult,
    Observation,
    ScenarioManifest,
    SemanticAction,
    VerificationResult,
)

try:
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

SCHEMA_DIR = ROOT / "interfaces" / "json_schema"
EXAMPLE_DIR = ROOT / "interfaces" / "examples"

# schema stem -> example filename. Every schema MUST be registered.
# None means the type is exercised inside another example rather than standing
# alone, and the reason is recorded next to it.
EXAMPLE_FOR_SCHEMA = {
    "action_result": "action-result-place-confirmed.json",
    "emotion_intent": "emotion-intent-uncertain.json",
    "mcu_protocol": "mcu-frame-stop-ack.json",
    "observation": "observation-red-block.json",
    "pose": None,  # embedded in observation and world_state examples
    "scenario": "scenario-normal-001.json",
    "semantic_action": "semantic-action-place.json",
    "task_graph": None,  # produced by the planner, covered by the round-trip check
    "verification_result": "verification-insufficient-evidence.json",
    "world_event": None,  # produced at runtime, covered by world model tests
    "world_state": "world-state-block-in-tray.json",
}

# example filename -> Pydantic model, where a model exists for it.
# ActionResult and VerificationResult are included because the reviewer found
# that the Pydantic models diverged from the schemas (completed vs status,
# status vs outcome) — full coverage makes that drift visible immediately.
MODEL_FOR_EXAMPLE = {
    "action-result-place-confirmed.json": ActionResult,
    "observation-red-block.json": Observation,
    "semantic-action-place.json": SemanticAction,
    "scenario-normal-001.json": ScenarioManifest,
    "verification-insufficient-evidence.json": VerificationResult,
}


def check_every_schema_is_registered() -> list[str]:
    on_disk = {p.name.removesuffix(".schema.json") for p in SCHEMA_DIR.glob("*.schema.json")}
    registered = set(EXAMPLE_FOR_SCHEMA)
    problems = []
    for stem in sorted(on_disk - registered):
        problems.append(
            f"{stem}.schema.json is not registered here; add an example for it, "
            "or register it as None with a reason"
        )
    for stem in sorted(registered - on_disk):
        problems.append(f"{stem} is registered here but no such schema exists")
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
    for stem, example_name in sorted(EXAMPLE_FOR_SCHEMA.items()):
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
    for stem, example_name in sorted(EXAMPLE_FOR_SCHEMA.items()):
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
    for example_name, model in sorted(MODEL_FOR_EXAMPLE.items()):
        path = EXAMPLE_DIR / example_name
        if not path.is_file():
            problems.append(f"{example_name}: file missing, cannot validate {model.__name__}")
            continue
        try:
            model.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{model.__name__} rejected {example_name}: {exc}")
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
        ("examples parse as JSON", check_examples_parse),
        ("required fields are defined", check_required_fields_are_defined),
        ("examples satisfy required fields", check_examples_satisfy_required),
        ("jsonschema Draft-2020-12 validation", check_jsonschema_validation),
        ("Pydantic models accept examples", check_models_accept_examples),
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
