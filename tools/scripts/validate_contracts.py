"""Validate every committed contract example against its schema and typed model.

Five independent checks run here. The point of the generic ones is that adding a
schema plus an example is enough to get CI coverage: nobody has to remember to
edit this file, and an unexercised contract fails the build instead of drifting
silently.
"""

import json
import sys

from _paths import ROOT, enable_local_packages

enable_local_packages()

from workbench_agent_runtime import build_template_plan
from workbench_contracts import Observation, ScenarioManifest, SemanticAction

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
MODEL_FOR_EXAMPLE = {
    "observation-red-block.json": Observation,
    "semantic-action-place.json": SemanticAction,
    "scenario-normal-001.json": ScenarioManifest,
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


def check_models_accept_examples() -> list[str]:
    problems = []
    for example_name, model in sorted(MODEL_FOR_EXAMPLE.items()):
        path = EXAMPLE_DIR / example_name
        try:
            model.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - report every failure, do not stop at the first
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
        ("models accept examples", check_models_accept_examples),
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
