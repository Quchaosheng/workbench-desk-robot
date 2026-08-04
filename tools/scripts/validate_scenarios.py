import json

from _paths import ROOT, enable_local_packages

enable_local_packages()

from workbench_contracts import ScenarioManifest


def main() -> int:
    scenario_files = sorted((ROOT / "sim" / "scenarios").rglob("*.json"))
    if not scenario_files:
        raise RuntimeError("no scenario manifests found")
    for path in scenario_files:
        ScenarioManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    print(f"scenario validation passed for {len(scenario_files)} manifest(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
