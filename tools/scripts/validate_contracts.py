import json
import sys

from _paths import ROOT, enable_local_packages

enable_local_packages()

from workbench_agent_runtime import build_template_plan
from workbench_contracts import Observation, SemanticAction


def main() -> int:
    examples = ROOT / "interfaces" / "examples"
    Observation.model_validate_json((examples / "observation-red-block.json").read_text(encoding="utf-8"))
    SemanticAction.model_validate_json((examples / "semantic-action-place.json").read_text(encoding="utf-8"))
    plan = build_template_plan("Place the red block in the tray")
    json.loads(plan.model_dump_json())
    print("contract validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
