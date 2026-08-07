from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "electrical-spec.json").read_text(encoding="utf-8"))
OUT = ROOT / "generated"


def calculate() -> dict[str, object]:
    rails = {rail["name"]: rail for rail in SPEC["rails"]}
    cases = {}
    for load_case in SPEC["load_cases"]:
        direct_loads: dict[str, float] = defaultdict(float)
        for load in SPEC["loads"]:
            watts = load_case["jetson_w"] if load["maximum_w"] == "LOAD_CASE" else load["maximum_w"]
            direct_loads[load["rail"]] += watts

        rail_demands = dict(direct_loads)
        for name, rail in rails.items():
            if rail["upstream"] is not None:
                upstream = rail["upstream"]
                rail_demands[upstream] = rail_demands.get(upstream, 0) + direct_loads[name] / rail["efficiency"]

        rail_results = {}
        for name, rail in rails.items():
            capacity_w = rail["voltage_v"] * rail["continuous_a"]
            demand_w = rail_demands.get(name, 0)
            rail_results[name] = {
                "capacity_w": capacity_w,
                "demand_w": round(demand_w, 2),
                "margin_over_demand_percent": round((capacity_w - demand_w) / demand_w * 100, 1),
                "pass": capacity_w >= demand_w * 1.2,
            }

        root_output_w = rail_demands["12V_ISO"]
        input_currents = {
            f"{voltage}V": round(root_output_w / rails["12V_ISO"]["efficiency"] / voltage, 2)
            for voltage in [
                SPEC["input"]["minimum_v"],
                SPEC["input"]["nominal_v"],
                SPEC["input"]["maximum_v"],
            ]
        }
        cases[load_case["name"]] = {
            "jetson_w": load_case["jetson_w"],
            "rail_results": rail_results,
            "input_currents_a": input_currents,
            "pass": all(result["pass"] for result in rail_results.values()),
        }

    worst_case = cases["JETSON_40W_MAXN"]
    input_current_at_min_v = worst_case["input_currents_a"][f'{SPEC["input"]["minimum_v"]}V']
    checks = {
        "all_load_cases_have_20_percent_headroom": all(case["pass"] for case in cases.values()),
        "input_current_below_fuse": input_current_at_min_v < SPEC["input"]["fuse_a"],
        "input_max_below_80v_components": SPEC["input"]["maximum_v"] < 80,
        "isolation_creepage_at_least_8mm": SPEC["dfm"]["isolation_creepage_mm"] >= 8,
        "can_has_120ohm_termination": SPEC["can"]["termination_ohm"] == 120,
        "all_rails_derated_from_rating": all(rail["continuous_a"] <= rail["rated_a"] for rail in rails.values()),
    }
    return {
        "status": "DESIGN_CHECK_ONLY_LAB_VALIDATION_REQUIRED",
        "load_cases": cases,
        "rail_results": worst_case["rail_results"],
        "maximum_documented_load_w": worst_case["rail_results"]["12V_ISO"]["demand_w"],
        "input_current_at_36v_a": input_current_at_min_v,
        "input_corner_currents_a": worst_case["input_currents_a"],
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
