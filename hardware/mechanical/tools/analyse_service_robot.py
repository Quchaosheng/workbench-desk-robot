from __future__ import annotations

import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
SPEC = json.loads((ROOT / "service-robot-product-baseline.json").read_text(encoding="utf-8"))


def analyse() -> dict[str, object]:
    with (ROOT / "service-robot-mass-ledger.csv").open(newline="", encoding="utf-8") as handle:
        mass_rows = list(csv.DictReader(handle))
    with (REPO / "hardware/release/service-robot-cost-target.csv").open(newline="", encoding="utf-8") as handle:
        cost_rows = list(csv.DictReader(handle))

    mass = sum(float(row["mass_kg"]) for row in mass_rows)
    cg = [sum(float(row["mass_kg"]) * float(row[f"{axis}_mm"]) for row in mass_rows) / mass for axis in ("x", "y", "z")]
    stabilizer = SPEC["stability"]["deployed_hidden_stabilizer_polygon_mm"]
    roll_tip = math.degrees(math.atan2(stabilizer[0] / 2 - abs(cg[0]), cg[2]))
    pitch_tip = math.degrees(math.atan2(stabilizer[1] / 2 - abs(cg[1]), cg[2]))
    evt_cost = sum(float(row["evt_target_usd"]) for row in cost_rows)
    production_cost = sum(float(row["production_100_target_usd"]) for row in cost_rows)

    mobility = SPEC["mobility"]
    radius_m = mobility["wheel_diameter_mm"] / 2000
    force_n = mass * (
        mobility["maximum_acceleration_mps2"] + 9.80665 * (0.02 + math.sin(math.radians(mobility["maximum_grade_deg"])))
    )
    required_torque_each = force_n * radius_m
    checks = {
        "mass_target_met": mass <= SPEC["target_mass_kg"],
        "evt_cost_target_met": evt_cost <= SPEC["cost_targets_usd"]["evt_unit_hardware_max"],
        "production_cost_target_met": production_cost <= SPEC["cost_targets_usd"]["production_100_unit_bom_max"],
        "two_seven_axis_arms": SPEC["arm"]["quantity"] == 2 and SPEC["arm"]["joint_count_each"] == 7,
        "drive_torque_screen_met": mobility["minimum_continuous_torque_nm_each"] >= required_torque_each * 2,
        "stabilized_tip_screen_met": min(roll_tip, pitch_tip) >= SPEC["stability"]["minimum_static_tip_screen_deg"],
        "physical_and_supplier_gates_open": bool(SPEC["release_blockers"]) and "VALIDATION_REQUIRED" in SPEC["status"],
    }
    return {
        "configuration_id": SPEC["configuration_id"],
        "status": SPEC["status"],
        "engineering_target_pass": all(checks.values()),
        "checks": checks,
        "mass_kg": round(mass, 1),
        "center_of_gravity_mm": [round(value, 1) for value in cg],
        "stabilized_tip_angles_deg": {"roll": round(roll_tip, 1), "pitch": round(pitch_tip, 1)},
        "required_drive_torque_nm_each_before_margin": round(required_torque_each, 1),
        "cost_targets_usd": {"evt": round(evt_cost), "production_100": round(production_cost)},
        "costs_are_quotes": False,
        "mass_is_measured": False,
        "release_blockers": SPEC["release_blockers"],
    }


def main() -> int:
    report = analyse()
    output = ROOT / "generated/service_robot_analysis.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))
    return 0 if report["engineering_target_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
