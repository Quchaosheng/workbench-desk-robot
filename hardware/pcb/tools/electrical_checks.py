from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "electrical-spec.json").read_text(encoding="utf-8"))
OUT = ROOT / "generated"


def calculate() -> dict[str, object]:
    rails = {rail["name"]: rail for rail in SPEC["rails"]}
    load_watts: dict[str, float] = defaultdict(float)
    for load in SPEC["loads"]:
        load_watts[load["rail"]] += load["maximum_w"]

    rail_results = {}
    for name, rail in rails.items():
        capacity_w = rail["voltage_v"] * rail["continuous_a"]
        demand_w = load_watts[name]
        rail_results[name] = {
            "capacity_w": capacity_w,
            "demand_w": demand_w,
            "margin_over_demand_percent": round((capacity_w - demand_w) / demand_w * 100, 1),
            "pass": capacity_w >= demand_w * 1.2,
        }

    output_w = sum(result["demand_w"] for result in rail_results.values())
    conservative_efficiency = min(rail["efficiency"] for rail in rails.values())
    input_current_at_min_v = output_w / conservative_efficiency / SPEC["input"]["minimum_v"]
    checks = {
        "all_rails_have_20_percent_headroom": all(item["pass"] for item in rail_results.values()),
        "input_current_below_fuse": input_current_at_min_v < SPEC["input"]["fuse_a"],
        "input_max_below_80v_components": SPEC["input"]["maximum_v"] < 80,
        "isolation_creepage_at_least_8mm": SPEC["dfm"]["isolation_creepage_mm"] >= 8,
        "can_has_120ohm_termination": SPEC["can"]["termination_ohm"] == 120,
    }
    return {
        "status": "DESIGN_CHECK_ONLY_LAB_VALIDATION_REQUIRED",
        "rail_results": rail_results,
        "maximum_documented_load_w": output_w,
        "input_current_at_36v_a": round(input_current_at_min_v, 2),
        "estimated_conversion_loss_w": round(output_w / conservative_efficiency - output_w, 1),
        "checks": checks,
        "pass": all(checks.values()),
    }


def main() -> None:
    OUT.mkdir(exist_ok=True)
    report = calculate()
    (OUT / "electrical_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["pass"]:
        raise SystemExit("electrical design check failed")


if __name__ == "__main__":
    main()
