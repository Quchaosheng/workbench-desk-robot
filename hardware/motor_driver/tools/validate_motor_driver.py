from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "hardware" / "motor_driver"
ENGINEERING_OUTPUT = PACKAGE / "generated" / "engineering-report.json"
RELEASE_OUTPUT = PACKAGE / "generated" / "release-readiness.json"

REQUIRED_FILES = [
    "README.md",
    "electrical-spec.json",
    "source-baseline.json",
    "architecture-options.csv",
    "motor-candidate-matrix.csv",
    "connector-pinout.csv",
    "safety-gate-truth-table.csv",
    "power-regen-budget.csv",
    "bom.csv",
    "component-approval-register.csv",
    "driver-pin-connectivity.csv",
    "verification-matrix.csv",
    "release-gates.csv",
    "placement-plan.csv",
    "kicad/README.md",
    "kicad/traction-childboard-concept.kicad_pcb",
    "generated/concept-drc.rpt",
    "generated/placement-review.svg",
]


def read_csv(name: str, package: Path = PACKAGE) -> list[dict[str, str]]:
    with (package / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_json(name: str, package: Path = PACKAGE) -> dict[str, Any]:
    return json.loads((package / name).read_text(encoding="utf-8"))


def approval_is_complete(row: dict[str, str]) -> bool:
    return row["decision"] == "APPROVED" and all(
        row[field].strip()
        for field in ("approved_mpn", "datasheet_revision", "approved_by", "approved_at", "evidence_ref")
    )


def validate_truth_table(rows: list[dict[str, str]]) -> dict[str, bool]:
    values = [{key: int(value) for key, value in row.items() if key != "required_behavior"} for row in rows]
    enable_inputs = ("safe_a_closed", "safe_b_closed", "manual_reset_complete", "drive_request", "driver_fault_free")
    return {
        "bridge_requires_every_permission": all(
            not row["bridge_output_permitted"] or all(row[key] for key in enable_inputs) for row in values
        ),
        "channel_a_dominates_nsleep": all(
            not row["nsleep_high_permitted"]
            or (row["safe_a_closed"] and row["manual_reset_complete"] and row["driver_fault_free"])
            for row in values
        ),
        "channel_b_dominates_enable": all(
            not row["en_high_permitted"]
            or (
                row["safe_b_closed"]
                and row["manual_reset_complete"]
                and row["drive_request"]
                and row["driver_fault_free"]
            )
            for row in values
        ),
        "channel_discrepancies_disable_and_latch": all(
            not row["bridge_output_permitted"] and row["fault_latched"]
            for row in values
            if row["safe_a_closed"] != row["safe_b_closed"]
        ),
        "software_bypass_cases_are_covered": {
            (row["safe_a_closed"], row["safe_b_closed"], row["drive_request"], row["bridge_output_permitted"])
            for row in values
        }
        >= {(0, 1, 1, 0), (1, 0, 1, 0)},
        "healthy_requested_case_is_covered": any(
            all(row[key] for key in enable_inputs) and row["bridge_output_permitted"] for row in values
        ),
    }


def parsed_candidate_pins(rows: list[dict[str, str]]) -> list[int]:
    return [int(pin) for row in rows for pin in row["pins"].split()]


def validate(package: Path = PACKAGE) -> dict[str, Any]:
    spec = load_json("electrical-spec.json", package)
    sources = load_json("source-baseline.json", package)["sources"]
    options = read_csv("architecture-options.csv", package)
    motor_candidates = read_csv("motor-candidate-matrix.csv", package)
    connectors = read_csv("connector-pinout.csv", package)
    truth_rows = read_csv("safety-gate-truth-table.csv", package)
    budget = read_csv("power-regen-budget.csv", package)
    bom = read_csv("bom.csv", package)
    approvals = read_csv("component-approval-register.csv", package)
    pins = read_csv("driver-pin-connectivity.csv", package)
    verification = read_csv("verification-matrix.csv", package)
    gates = read_csv("release-gates.csv", package)
    placement = read_csv("placement-plan.csv", package)
    layout = spec["layout_concept"]
    pin_numbers = parsed_candidate_pins(pins)
    budget_by_id = {row["parameter_id"]: row for row in budget}
    connector_signals = {row["signal"] for row in connectors}
    release_blockers = [row["gate_id"] for row in gates if row["release_blocker"] == "yes"]
    required_budget_tbd = {
        "PWR-004",
        "PWR-005",
        "PWR-006",
        "PWR-007",
        "PWR-008",
        "PWR-009",
        "PWR-010",
        "PWR-011",
        "PWR-012",
        "REG-001",
        "REG-002",
        "REG-003",
        "REG-004",
        "REG-005",
        "REG-006",
        "THM-001",
        "THM-002",
        "THM-003",
    }
    required_gate_ids = {
        "MTR-MOTOR",
        "MTR-POWER",
        "MTR-DRV",
        "MTR-REGEN",
        "MTR-CURRENT",
        "MTR-SAFETY",
        "MTR-CONTROL",
        "MTR-SCHEMATIC",
        "MTR-LAYOUT",
        "MTR-THERMAL",
        "MTR-HARNESS",
        "MTR-DFM",
        "MTR-BRINGUP",
    }
    board = (package / "kicad/traction-childboard-concept.kicad_pcb").read_text(encoding="utf-8")
    concept_drc = (package / "generated/concept-drc.rpt").read_text(encoding="utf-8")
    checks = {
        "required_files_exist": all((package / name).is_file() for name in REQUIRED_FILES),
        "two_brushed_axes_only": spec["scope"]["traction_axis_count"] == 2
        and spec["scope"]["review_motor_technology"] == "BRUSHED_DC_GEARMOTOR"
        and spec["scope"]["motor_mpn"] is None
        and not spec["scope"]["controls_ur5e_joint_motors"]
        and not spec["scope"]["controls_robotiq_gripper"],
        "review_baseline_is_12v_j2_not_production_selection": spec["power"]["selected_review_baseline"]
        == "12V_AUX_FROM_CONTROLLER_J2"
        and spec["power"]["production_architecture"] is None
        and spec["release_status"] == "DO_NOT_ORDER",
        "j2_power_ceiling_is_consistent": spec["power"]["nominal_input_v"] == 12
        and spec["power"]["aggregate_input_power_limit_w"] == 120
        and spec["power"]["aggregate_input_current_limit_a"]
        == spec["power"]["aggregate_input_power_limit_w"] / spec["power"]["nominal_input_v"]
        and budget_by_id["PWR-003"]["value"] == "10",
        "motor_power_inputs_remain_unknown": all(
            spec["power"][field] is None
            for field in (
                "motor_winding_nominal_v",
                "motor_continuous_current_each_a",
                "motor_stall_current_each_a",
                "simultaneous_axis_duty_cycle",
                "branch_fuse_rating_a",
            )
        ),
        "pololu_motor_is_candidate_not_production_selection": len(motor_candidates) == 1
        and motor_candidates[0]["manufacturer"] == "Pololu"
        and motor_candidates[0]["mpn"] == "4753"
        and motor_candidates[0]["selection_status"] == "CANDIDATE_NOT_APPROVED"
        and motor_candidates[0]["production_selected"] == "no"
        and spec["scope"]["motor_mpn"] is None
        and spec["motor_candidates"][0]["candidate_mpn"] == "4753"
        and not spec["motor_candidates"][0]["production_selected"],
        "candidate_fits_envelope_analytically": all(
            candidate <= envelope
            for candidate, envelope in zip(
                spec["motor_candidates"][0]["candidate_fit_envelope_mm"],
                spec["motor_candidates"][0]["mechanical_envelope_mm"],
                strict=True,
            )
        )
        and spec["motor_candidates"][0]["fit_status"] == "ANALYTICAL_CANDIDATE_ONLY",
        "candidate_dual_stall_exceeds_j2_ceiling": spec["motor_candidates"][0]["simultaneous_two_axis_stall_current_a"]
        == 2 * spec["motor_candidates"][0]["stall_current_a"]
        and spec["motor_candidates"][0]["simultaneous_two_axis_stall_current_a"]
        > spec["power"]["aggregate_input_current_limit_a"]
        and budget_by_id["PWR-015"]["value"] == "11.0"
        and budget_by_id["PWR-015"]["status"] == "CANDIDATE_EXCEEDS_J2_LIMIT"
        and budget_by_id["PWR-015"]["release_blocker"] == "yes",
        "regeneration_is_fail_closed": not spec["power"]["source_sink_capability_confirmed"]
        and spec["power"]["must_not_return_regeneration_to_j2"]
        and spec["regeneration"]["status"] == "TBD_BLOCKING"
        and all(value is None for key, value in spec["regeneration"].items() if key != "status"),
        "drv8962_is_candidate_not_board_rating": spec["driver_candidate"]["candidate_mpn"] == "DRV8962DDVR"
        and spec["driver_candidate"]["approval_status"] == "CANDIDATE_NOT_APPROVED"
        and spec["driver_candidate"]["operating_supply_min_v"] == 4.5
        and spec["driver_candidate"]["operating_supply_max_v"] == 65
        and spec["driver_candidate"]["datasheet_current_per_output_a"] == 10
        and not spec["driver_candidate"]["datasheet_current_is_board_rating"],
        "architecture_options_keep_both_paths_blocked": {row["option_id"] for row in options}
        == {"MTR-ARCH-12V", "MTR-ARCH-48V"}
        and all(row["production_selected"] == "no" for row in options)
        and all("BLOCK" in row["review_state"] or row["review_state"] == "SELECTED_FOR_REVIEW" for row in options),
        "j2_power_pinout_is_complete": {
            (row["pin"], row["signal"]) for row in connectors if row["reference"] == "J_PWR"
        }
        == {
            ("1", "12V_MOTOR_AUX"),
            ("2", "12V_MOTOR_AUX"),
            ("3", "GND_MOTOR"),
            ("4", "GND_MOTOR"),
        },
        "can_isolation_domain_is_preserved": {
            (row["pin"], row["signal"]) for row in connectors if row["reference"] == "J_CAN"
        }
        == {("1", "CANH"), ("2", "CANL"), ("3", "GND_CAN_ISO"), ("4", "NC")}
        and spec["control"]["can_interface_isolation_required"]
        and spec["control"]["gnd_can_iso_must_not_connect_to_gnd_motor"],
        "dual_safety_interface_is_explicit": {"SAFE_ENABLE_A", "SAFE_RETURN_A", "SAFE_ENABLE_B", "SAFE_RETURN_B"}
        <= connector_signals
        and spec["safety"]["independent_hardware_channels"] == 2
        and not spec["safety"]["existing_j11_is_compatible"]
        and "ESTOP_SENSE" not in {row["signal"] for row in connectors if row["domain"] == "safety"},
        "software_has_no_safety_authority": not spec["safety"]["software_can_assert_safety_permission"]
        and spec["safety"]["either_channel_open_disables_both_axes"]
        and not spec["control"]["drv8962_has_spi"]
        and not spec["control"]["motor_cs_signals_are_usable_as_drv8962_spi"],
        "truth_table_is_fail_closed": all(validate_truth_table(truth_rows).values()),
        "critical_budget_inputs_are_blank_blockers": required_budget_tbd <= budget_by_id.keys()
        and all(
            budget_by_id[item]["value"] == ""
            and budget_by_id[item]["status"] == "TBD_BLOCKING"
            and budget_by_id[item]["release_blocker"] == "yes"
            for item in required_budget_tbd
        ),
        "bom_and_approval_register_match": {row["reference"] for row in bom} == {row["reference"] for row in approvals}
        and all(row["candidate_mpn_or_class"] for row in bom),
        "no_component_is_falsely_approved": not any(approval_is_complete(row) for row in approvals)
        and all(row["decision"] == "PENDING" for row in approvals)
        and all(not row["approved_mpn"].strip() for row in approvals),
        "candidate_pinout_covers_ddv_exactly_once": sorted(pin_numbers) == list(range(1, 45))
        and len(pin_numbers) == len(set(pin_numbers))
        and all(row["freeze_status"] == "CANDIDATE_PINOUT" for row in pins),
        "candidate_pinout_preserves_independent_safety_gates": next(row for row in pins if row["pin_name"] == "nSLEEP")[
            "controlled_net"
        ]
        == "NSLEEP_SAFE_A"
        and {row["controlled_net"] for row in pins if row["pin_name"] in {"EN1", "EN2", "EN3", "EN4"}}
        == {"EN1_SAFE_B", "EN2_SAFE_B", "EN3_SAFE_B", "EN4_SAFE_B"},
        "all_physical_verification_is_not_executed": len(verification) >= 10
        and all(
            row["status"] == "NOT_EXECUTED"
            and row["evidence_ref"] == "NOT_ATTACHED"
            and row["release_blocker"] == "yes"
            for row in verification
        ),
        "release_gate_register_is_fail_closed": len(gates) == len({row["gate_id"] for row in gates})
        and required_gate_ids <= set(release_blockers)
        and all(row["status"] == "BLOCKED" for row in gates if row["release_blocker"] == "yes")
        and all((ROOT / row["evidence_ref"]).is_file() for row in gates if row["status"] == "PASS"),
        "layout_matches_mechanical_envelope": layout["board_width_mm"] == 118
        and layout["board_height_mm"] == 82
        and layout["mounting_pattern_mm"] == [108, 72]
        and layout["mounting_hole_count"] == 4
        and layout["mounting_hole_diameter_mm"] == 3.2
        and layout["maximum_assembly_height_mm"] == 20,
        "placement_blocks_fit_board_and_remain_conceptual": all(
            float(row["width_mm"]) / 2 <= float(row["x_mm"]) <= layout["board_width_mm"] - float(row["width_mm"]) / 2
            and float(row["height_mm"]) / 2
            <= float(row["y_mm"])
            <= layout["board_height_mm"] - float(row["height_mm"]) / 2
            and row["freeze_status"] == "CONCEPT_ONLY"
            for row in placement
        ),
        "concept_board_is_mechanical_only": "CONCEPT ONLY - NO ELECTRICAL FOOTPRINTS - DO NOT ORDER" in board
        and board.count('(property "Reference" "H') == 4
        and board.count("(segment") == 0
        and board.count("(zone") == 0
        and "Found 0 DRC violations" in concept_drc
        and "Found 0 unconnected pads" in concept_drc,
        "sources_are_traceable_not_approval": any(
            row["id"] == "SRC-TI-DRV8962-DS"
            and row["url"] == "https://www.ti.com/lit/ds/symlink/drv8962.pdf"
            and row["freeze_status"] == "CANDIDATE_SOURCE_ONLY"
            for row in sources
        )
        and {
            "SRC-POLOLU-4753-PRODUCT",
            "SRC-POLOLU-37D-DATASHEET",
        }
        <= {row["id"] for row in sources}
        and all(row["freeze_status"] != "APPROVED" for row in sources),
    }
    engineering_pass = all(checks.values())
    return {
        "package": spec["package"],
        "revision": spec["revision"],
        "engineering_package_pass": engineering_pass,
        "order_release_ready": False,
        "status": "ORDER_RELEASE_BLOCKED",
        "checks": checks,
        "metrics": {
            "traction_axes": spec["scope"]["traction_axis_count"],
            "j2_power_ceiling_w": spec["power"]["aggregate_input_power_limit_w"],
            "j2_current_ceiling_a": spec["power"]["aggregate_input_current_limit_a"],
            "candidate_driver_count": 1,
            "candidate_motor_count": len(motor_candidates),
            "candidate_dual_stall_current_a": spec["motor_candidates"][0]["simultaneous_two_axis_stall_current_a"],
            "controlled_driver_pin_count": len(pin_numbers),
            "release_gate_count": len(gates),
            "release_blocker_count": len(release_blockers),
            "verification_item_count": len(verification),
            "board_envelope_mm": [
                layout["board_width_mm"],
                layout["board_height_mm"],
                layout["maximum_assembly_height_mm"],
            ],
            "mounting_pattern_mm": layout["mounting_pattern_mm"],
        },
        "release_blockers": release_blockers,
        "truth_table_checks": validate_truth_table(truth_rows),
        "note": "Engineering consistency does not approve procurement, safety, fabrication, or physical operation.",
    }


def write_reports(report: dict[str, Any]) -> None:
    ENGINEERING_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    ENGINEERING_OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    release = {
        "package": report["package"],
        "revision": report["revision"],
        "engineering_package_pass": report["engineering_package_pass"],
        "order_release_ready": report["order_release_ready"],
        "status": report["status"],
        "blocker_count": len(report["release_blockers"]),
        "blockers": report["release_blockers"],
        "note": (
            "Blockers close only with named approvals and attached external evidence; "
            "repository edits cannot infer them."
        ),
    }
    RELEASE_OUTPUT.write_text(json.dumps(release, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    report = validate()
    write_reports(report)
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["engineering_package_pass"] else 1)


if __name__ == "__main__":
    main()
