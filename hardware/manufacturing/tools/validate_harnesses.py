from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "harness-spec.csv"
OUT = ROOT / "generated/harness_report.json"
MOTOR_SPEC = ROOT.parent / "motor_driver/electrical-spec.json"
COPPER_RESISTIVITY_OHM_MM2_PER_M = 0.0175
BASELINE_HARNESS_IDS = {f"H{index:02d}" for index in range(1, 9)}
TRACTION_HARNESS_IDS = {f"H{index:02d}" for index in range(9, 15)}
TRACTION_INTERFACE_BY_ID = {
    "H09": "J_SAFE",
    "H10": "J_CAN",
    "H11": "J_ML",
    "H12": "J_MR",
    "H13": "J_ENC_L",
    "H14": "J_ENC_R",
}


def _motor_power_budget() -> tuple[float, float, bool]:
    """Return candidate dual-stall current, J2 ceiling, and fail-closed status."""
    with MOTOR_SPEC.open(encoding="utf-8") as handle:
        spec = json.load(handle)
    candidate = spec["motor_candidates"][0]
    stall_current = float(candidate["simultaneous_two_axis_stall_current_a"])
    j2_ceiling = float(spec["power"]["aggregate_input_current_limit_a"])
    report_is_blocked = spec["release_status"] == "DO_NOT_ORDER" and not candidate["production_selected"]
    return stall_current, j2_ceiling, report_is_blocked


def calculate_row(row: dict[str, str]) -> dict[str, object]:
    """Calculate electrical and service checks for one controlled harness row."""
    length_m = float(row["length_m"])
    voltage_v = float(row["voltage_v"])
    current_a = float(row["max_current_a"])
    area_mm2 = float(row["copper_area_mm2"])
    supply_count = int(row["parallel_supply"])
    return_count = int(row["parallel_return"])
    supply_resistance = COPPER_RESISTIVITY_OHM_MM2_PER_M * length_m / (area_mm2 * supply_count)
    return_resistance = COPPER_RESISTIVITY_OHM_MM2_PER_M * length_m / (area_mm2 * return_count)
    voltage_drop_v = current_a * (supply_resistance + return_resistance)
    drop_percent = voltage_drop_v / voltage_v * 100
    current_density = current_a / (area_mm2 * min(supply_count, return_count))
    declared_bend_radius = float(row["min_bend_radius_mm"])
    required_bend_radius = float(row.get("required_bend_radius_mm") or row["min_bend_radius_mm"])
    return {
        "harness_id": row["harness_id"],
        "voltage_drop_v": round(voltage_drop_v, 3),
        "voltage_drop_percent": round(drop_percent, 2),
        "current_density_a_per_mm2": round(current_density, 2),
        "drop_pass": drop_percent <= 3.0,
        "current_density_pass": current_density <= 6.0,
        "declared_bend_radius_mm": declared_bend_radius,
        "required_bend_radius_mm": required_bend_radius,
        "bend_radius_pass": declared_bend_radius >= required_bend_radius and declared_bend_radius <= 20,
        "shield_required_and_defined": row["harness_id"] not in {"H04", "H05", "H06", "H07", "H08"}
        or row["shield"] != "no",
    }


def validate() -> dict[str, object]:
    with SPEC.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    all_results = []
    for row in rows:
        all_results.append(calculate_row(row))

    baseline_rows = [row for row in rows if row["harness_id"] in BASELINE_HARNESS_IDS]
    traction_rows = [row for row in rows if row["harness_id"] in TRACTION_HARNESS_IDS]
    results = [item for item in all_results if item["harness_id"] in BASELINE_HARNESS_IDS]
    traction_results = [item for item in all_results if item["harness_id"] in TRACTION_HARNESS_IDS]
    candidate_stall_current, j2_current_ceiling, motor_budget_is_fail_closed = _motor_power_budget()
    h02 = next((row for row in baseline_rows if row["harness_id"] == "H02"), {})
    motor_harness_rows = [row for row in traction_rows if row["harness_id"] in {"H11", "H12"}]
    cross_package_checks = {
        "motor_spec_is_fail_closed": motor_budget_is_fail_closed,
        "candidate_dual_stall_exceeds_j2_ceiling": candidate_stall_current > j2_current_ceiling,
        "j2_harness_row_matches_controller_ceiling": h02.get("max_current_a") == str(int(j2_current_ceiling)),
        "motor_harness_rows_preserve_candidate_current": all(
            row.get("max_current_a") == "5.5" and row.get("mating_part_status") == "MPN_REQUIRED"
            for row in motor_harness_rows
        ),
        "candidate_stall_is_explicit_release_blocker": candidate_stall_current > j2_current_ceiling,
    }
    engineering_checks = {
        "eight_controlled_harnesses": len(baseline_rows) == 8,
        "unique_harness_ids": len({row["harness_id"] for row in rows}) == len(rows),
        "all_voltage_drops_within_3_percent": all(item["drop_pass"] for item in all_results),
        "all_current_density_within_6a_per_mm2": all(item["current_density_pass"] for item in all_results),
        "all_bend_radii_fit_20mm_service_margin": all(item["bend_radius_pass"] for item in all_results),
        "minimum_bend_radius_is_explicit": all(row.get("required_bend_radius_mm", "").strip() for row in rows),
        "signal_and_safety_harness_shields_defined": all(item["shield_required_and_defined"] for item in all_results),
        "traction_harness_ids_complete": {row["harness_id"] for row in traction_rows} == TRACTION_HARNESS_IDS
        and len(traction_rows) == len(TRACTION_HARNESS_IDS),
        "traction_interfaces_cover_childboard": {row["harness_id"]: row["to_interface"] for row in traction_rows}
        == TRACTION_INTERFACE_BY_ID,
        "traction_safety_eco_is_explicit": all(
            row["from_ref"] == "J10-ECO" and row["mating_part_status"] == "MPN_REQUIRED" and row["shield"] == "overall"
            for row in traction_rows
            if row["harness_id"] == "H09"
        ),
        "traction_motor_rows_remain_candidate_limits": all(
            row["mating_part_status"] == "MPN_REQUIRED" and row["max_current_a"] == "5.5" and row["awg"] == "14"
            for row in traction_rows
            if row["harness_id"] in {"H11", "H12"}
        ),
        "traction_motor_bend_radius_is_20mm": all(
            item["required_bend_radius_mm"] >= 20 and item["bend_radius_pass"]
            for item in traction_results
            if item["harness_id"] in {"H11", "H12"}
        ),
        "cross_package_motor_budget_is_explicit": all(cross_package_checks.values()),
    }
    release_checks = {
        "all_mating_parts_approved": all(row["mating_part_status"] == "APPROVED" for row in rows),
        "physical_continuity_and_pull_test_attached": False,
        "installed_length_and_chafe_check_attached": False,
        "candidate_dual_stall_within_j2_ceiling": candidate_stall_current <= j2_current_ceiling,
    }
    return {
        "status": "HARNESS_RELEASE_BLOCKED" if not all(release_checks.values()) else "HARNESS_RELEASED",
        "engineering_package_pass": all(engineering_checks.values()),
        "engineering_checks": engineering_checks,
        "release_checks": release_checks,
        "results": results,
        "traction_results": traction_results,
        "all_results": all_results,
        "traction_engineering_checks": {
            key: value for key, value in engineering_checks.items() if key.startswith("traction_")
        },
        "cross_package_checks": cross_package_checks,
        "power_budget": {
            "candidate_dual_stall_current_a": candidate_stall_current,
            "j2_aggregate_current_ceiling_a": j2_current_ceiling,
            "status": "BLOCKED_CANDIDATE_EXCEEDS_J2_LIMIT"
            if candidate_stall_current > j2_current_ceiling
            else "REVIEW",
        },
    }


def main() -> None:
    report = validate()
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["engineering_package_pass"]:
        raise SystemExit("harness engineering checks failed")


if __name__ == "__main__":
    main()
