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
INTEGRATION_HARNESS_IDS = {"H02", *TRACTION_HARNESS_IDS}
TRACTION_INTERFACE_BY_ID = {
    "H02": "J_PWR",
    "H09": "J_SAFE",
    "H10": "J_CAN",
    "H11": "J_ML",
    "H12": "J_MR",
    "H13": "J_ENC_L",
    "H14": "J_ENC_R",
}
EXPECTED_ENDPOINTS_BY_ID = {
    "H02": ("CONTROLLER_J2", "TRACTION_CHILDBOARD_J_PWR"),
    "H09": ("CONTROLLER_J10_K1_K2_SAFETY_ECO", "TRACTION_CHILDBOARD_J_SAFE"),
    "H10": ("CONTROLLER_J5_OR_J6_ISOLATED_CAN", "TRACTION_CHILDBOARD_J_CAN"),
    "H11": ("TRACTION_CHILDBOARD_J_ML", "M1_LEFT_TRACTION_MOTOR"),
    "H12": ("TRACTION_CHILDBOARD_J_MR", "M2_RIGHT_TRACTION_MOTOR"),
    "H13": ("TRACTION_CHILDBOARD_J_ENC_L", "M1_LEFT_ENCODER"),
    "H14": ("TRACTION_CHILDBOARD_J_ENC_R", "M2_RIGHT_ENCODER"),
}
EXPECTED_PIN_MAP_BY_ID = {
    "H02": "J2.1->J_PWR.1;J2.2->J_PWR.2;J2.3->J_PWR.3;J2.4->J_PWR.4",
    "H09": "J10-ECO.A_OUT->J_SAFE.1;J10-ECO.A_RETURN->J_SAFE.2;J10-ECO.B_OUT->J_SAFE.3;J10-ECO.B_RETURN->J_SAFE.4",
    "H10": "J5/J6.1->J_CAN.1;J5/J6.2->J_CAN.2;J5/J6.3->J_CAN.3;SHIELD_DRAIN->DRAIN_TERMINATION_TBD",
    "H11": "J_ML.1->M1.TERM_A;J_ML.2->M1.TERM_B",
    "H12": "J_MR.1->M2.TERM_A;J_MR.2->M2.TERM_B",
    "H13": "J_ENC_L.1->M1.ENC_VCC;J_ENC_L.2->M1.ENC_GND;J_ENC_L.3->M1.ENC_A;J_ENC_L.4->M1.ENC_B",
    "H14": "J_ENC_R.1->M2.ENC_VCC;J_ENC_R.2->M2.ENC_GND;J_ENC_R.3->M2.ENC_A;J_ENC_R.4->M2.ENC_B",
}
EXPECTED_ACTIVE_SEMANTICS_BY_ID = {
    "H02": "12V_MOTOR_AUX_DC",
    "H09": "DUAL_CHANNEL_HARDWIRED_SAFETY_PERMISSIVE",
    "H10": "CAN_FD_DIFFERENTIAL",
    "H11": "BIDIRECTIONAL_BRUSHED_MOTOR_OUTPUT",
    "H12": "BIDIRECTIONAL_BRUSHED_MOTOR_OUTPUT",
    "H13": "QUADRATURE_ENCODER_LEVEL_TBD",
    "H14": "QUADRATURE_ENCODER_LEVEL_TBD",
}
EXPECTED_SHIELD_SEMANTICS_BY_ID = {
    "H02": "UNSHIELDED_POWER",
    "H09": "OVERALL_BRAID",
    "H10": "BRAID",
    "H11": "UNSHIELDED_HIGH_CURRENT_PAIR",
    "H12": "UNSHIELDED_HIGH_CURRENT_PAIR",
    "H13": "BRAID",
    "H14": "BRAID",
}
EXPECTED_DRAIN_SEMANTICS_BY_ID = {
    "H02": "NONE",
    "H09": "DRAIN_TO_CHASSIS_AT_CONTROLLER_ONLY_TBD",
    "H10": "DRAIN_TO_CHASSIS_AT_CABLE_ENTRY_TBD",
    "H11": "NONE",
    "H12": "NONE",
    "H13": "DRAIN_TO_CHASSIS_AT_CABLE_ENTRY_TBD",
    "H14": "DRAIN_TO_CHASSIS_AT_CABLE_ENTRY_TBD",
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
        "shield_required_and_defined": bool(row.get("shield", "").strip())
        and bool(row.get("shield_semantics", "").strip())
        and bool(row.get("drain_semantics", "").strip()),
        "source_endpoint": row.get("source_endpoint", ""),
        "destination_endpoint": row.get("destination_endpoint", ""),
        "pin_map": row.get("pin_map", ""),
        "active_semantics": row.get("active_semantics", ""),
        "shield_semantics": row.get("shield_semantics", ""),
        "drain_semantics": row.get("drain_semantics", ""),
    }


def _integration_semantics_checks(rows: list[dict[str, str]]) -> dict[str, bool]:
    """Validate endpoint, pin-map, active-level and shield semantics for the traction path."""
    by_id = {row.get("harness_id", ""): row for row in rows}
    required_fields = {
        "source_endpoint",
        "destination_endpoint",
        "pin_map",
        "active_semantics",
        "shield_semantics",
        "drain_semantics",
        "signal_conductors",
        "shield_conductors",
    }
    fields_present = all(required_fields <= row.keys() for row in rows)
    endpoint_fields_complete = all(
        row.get("source_endpoint", "").strip()
        and row.get("destination_endpoint", "").strip()
        and row.get("source_endpoint") != row.get("destination_endpoint")
        for row in rows
    )
    pin_maps_complete = all(
        row.get("pin_map", "").strip()
        and all(
            "->" in mapping and mapping.split("->", 1)[0] and mapping.split("->", 1)[1]
            for mapping in row["pin_map"].split(";")
        )
        for row in rows
    )
    conductor_counts_reconcile = True
    for row in rows:
        try:
            conductor_counts_reconcile &= (
                int(row["signal_conductors"]) + int(row["shield_conductors"]) == int(row["conductors"])
                and int(row["signal_conductors"]) > 0
                and int(row["shield_conductors"]) >= 0
            )
        except (KeyError, TypeError, ValueError):
            conductor_counts_reconcile = False
    integration_rows = [by_id.get(harness_id, {}) for harness_id in INTEGRATION_HARNESS_IDS]
    endpoint_contract = all(
        row.get("source_endpoint") == EXPECTED_ENDPOINTS_BY_ID[harness_id][0]
        and row.get("destination_endpoint") == EXPECTED_ENDPOINTS_BY_ID[harness_id][1]
        for harness_id, row in by_id.items()
        if harness_id in EXPECTED_ENDPOINTS_BY_ID
    ) and all(row for row in integration_rows)
    pin_map_contract = all(
        by_id.get(harness_id, {}).get("pin_map") == expected for harness_id, expected in EXPECTED_PIN_MAP_BY_ID.items()
    )
    active_contract = all(
        by_id.get(harness_id, {}).get("active_semantics") == expected
        for harness_id, expected in EXPECTED_ACTIVE_SEMANTICS_BY_ID.items()
    )
    shield_contract = all(
        by_id.get(harness_id, {}).get("shield_semantics") == expected
        and by_id.get(harness_id, {}).get("drain_semantics") == EXPECTED_DRAIN_SEMANTICS_BY_ID[harness_id]
        for harness_id, expected in EXPECTED_SHIELD_SEMANTICS_BY_ID.items()
    )
    return {
        "fourteen_harness_rows_are_present": len(rows) == 14
        and {row.get("harness_id") for row in rows} == {f"H{index:02d}" for index in range(1, 15)},
        "endpoint_semantics_fields_are_present": fields_present and endpoint_fields_complete,
        "pin_maps_are_well_formed": pin_maps_complete,
        "signal_and_shield_conductor_counts_reconcile": conductor_counts_reconcile,
        "traction_endpoint_contract_is_explicit": endpoint_contract,
        "traction_pin_maps_match_controlled_interfaces": pin_map_contract,
        "traction_active_semantics_are_explicit": active_contract,
        "traction_shield_and_drain_semantics_are_explicit": shield_contract,
    }


def validate() -> dict[str, object]:
    with SPEC.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    all_results = []
    for row in rows:
        all_results.append(calculate_row(row))

    baseline_rows = [row for row in rows if row["harness_id"] in BASELINE_HARNESS_IDS]
    traction_rows = [row for row in rows if row["harness_id"] in TRACTION_HARNESS_IDS]
    integration_rows = [row for row in rows if row["harness_id"] in INTEGRATION_HARNESS_IDS]
    results = [item for item in all_results if item["harness_id"] in BASELINE_HARNESS_IDS]
    traction_results = [item for item in all_results if item["harness_id"] in TRACTION_HARNESS_IDS]
    integration_results = [item for item in all_results if item["harness_id"] in INTEGRATION_HARNESS_IDS]
    candidate_stall_current, j2_current_ceiling, motor_budget_is_fail_closed = _motor_power_budget()
    h02 = next((row for row in baseline_rows if row["harness_id"] == "H02"), {})
    motor_harness_rows = [row for row in traction_rows if row["harness_id"] in {"H11", "H12"}]
    cross_package_checks = {
        "motor_spec_is_fail_closed": motor_budget_is_fail_closed,
        "candidate_dual_stall_exceeds_j2_ceiling": candidate_stall_current > j2_current_ceiling,
        "j2_harness_row_matches_controller_ceiling": h02.get("max_current_a") == str(int(j2_current_ceiling))
        and h02.get("to_interface") == "J_PWR"
        and h02.get("pin_map") == EXPECTED_PIN_MAP_BY_ID["H02"],
        "motor_harness_rows_preserve_candidate_current": all(
            row.get("max_current_a") == "5.5" and row.get("mating_part_status") == "MPN_REQUIRED"
            for row in motor_harness_rows
        ),
        "candidate_stall_is_explicit_release_blocker": candidate_stall_current > j2_current_ceiling,
    }
    integration_semantics_checks = _integration_semantics_checks(rows)
    engineering_checks = {
        "eight_controlled_harnesses": len(baseline_rows) == 8,
        "unique_harness_ids": len({row["harness_id"] for row in rows}) == len(rows),
        "all_voltage_drops_within_3_percent": all(item["drop_pass"] for item in all_results),
        "all_current_density_within_6a_per_mm2": all(item["current_density_pass"] for item in all_results),
        "all_bend_radii_fit_20mm_service_margin": all(item["bend_radius_pass"] for item in all_results),
        "minimum_bend_radius_is_explicit": all(row.get("required_bend_radius_mm", "").strip() for row in rows),
        "signal_and_safety_harness_shields_defined": all(item["shield_required_and_defined"] for item in all_results),
        "all_fourteen_harnesses_are_evaluated": len(all_results) == 14
        and len({item["harness_id"] for item in all_results}) == 14,
        "traction_harness_ids_complete": {row["harness_id"] for row in traction_rows} == TRACTION_HARNESS_IDS
        and len(traction_rows) == len(TRACTION_HARNESS_IDS),
        "traction_interfaces_cover_childboard": {row["harness_id"]: row["to_interface"] for row in integration_rows}
        == TRACTION_INTERFACE_BY_ID,
        "traction_safety_eco_is_explicit": all(
            row["from_ref"] == "J10-ECO"
            and row["source_endpoint"] == "CONTROLLER_J10_K1_K2_SAFETY_ECO"
            and row["destination_endpoint"] == "TRACTION_CHILDBOARD_J_SAFE"
            and row["mating_part_status"] == "MPN_REQUIRED"
            and row["shield"] == "overall"
            and row["to_interface"] == "J_SAFE"
            for row in traction_rows
            if row["harness_id"] == "H09"
        )
        and all(
            row["source_endpoint"] == "CONTROLLER_J11_CURRENT"
            and row["destination_endpoint"] == "UNDEFINED_SINGLE_CHANNEL_DRIVER_ENDPOINT"
            for row in rows
            if row["harness_id"] == "H08"
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
        **integration_semantics_checks,
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
        "integration_results": integration_results,
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
