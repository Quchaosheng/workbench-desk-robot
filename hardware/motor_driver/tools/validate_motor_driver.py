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
    "net-topology.csv",
    "safety-gate-connectivity.csv",
    "schematic-design.md",
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


def validate_net_topology(rows: list[dict[str, str]]) -> dict[str, bool]:
    by_id = {row.get("topology_id", ""): row for row in rows}
    required_ids = {
        "PWR-01",
        "PWR-02",
        "PWR-03",
        "PWR-04",
        "PWR-05",
        "PWR-06",
        "PWR-07",
        "PWR-08",
        "PWR-09",
        "PWR-10",
        "PWR-11",
        "PWR-12",
        "PWR-13",
        "CTRL-01",
        "CTRL-02",
        "CTRL-03",
        "CTRL-04",
        "CTRL-05",
        "CTRL-06",
        "CTRL-07",
        "BUS-01",
    }
    pwr01 = by_id.get("PWR-01", {})
    pwr02 = by_id.get("PWR-02", {})
    pwr03 = by_id.get("PWR-03", {})
    pwr04 = by_id.get("PWR-04", {})
    pwr05 = by_id.get("PWR-05", {})
    pwr06 = by_id.get("PWR-06", {})
    pwr07 = by_id.get("PWR-07", {})
    pwr09 = by_id.get("PWR-09", {})
    pwr10 = by_id.get("PWR-10", {})
    pwr11 = by_id.get("PWR-11", {})

    def endpoint_tokens(row: dict[str, str], field: str) -> set[str]:
        return {token.strip() for token in row.get(field, "").split(";") if token.strip()}

    endpoint_overlap_free = all(
        endpoint_tokens(row, "source_endpoints").isdisjoint(endpoint_tokens(row, "load_endpoints")) for row in rows
    )
    isolated_rows = [row for row in rows if row.get("domain") == "isolated_power" or row.get("barrier_id") == "U7"]
    isolated_endpoint_tokens = {
        token
        for row in isolated_rows
        for field in ("source_endpoints", "load_endpoints")
        for token in endpoint_tokens(row, field)
    }
    local_ground_tokens = {"GND_MOTOR", "GND_LOGIC", "STAR_GND_01"}
    return {
        "required_power_rows_present": required_ids <= set(by_id),
        "topology_ids_are_unique": len(by_id) == len(rows) and "" not in by_id,
        "input_is_protected_before_motor_bus": (
            pwr01.get("net_name") == "12V_MOTOR_AUX"
            and pwr01.get("net_role") == "source_input"
            and "J_PWR.1" in pwr01.get("source_endpoints", "")
            and "F1.1" in pwr01.get("load_endpoints", "")
            and pwr02.get("net_name") == "FUSED_12V"
            and pwr02.get("net_role") == "protection_input"
            and pwr02.get("source_endpoints") == "F1.2"
            and pwr02.get("load_endpoints") == "Q1.IN"
            and pwr03.get("net_name") == "VM_PROTECTED"
            and pwr03.get("source_endpoints") == "Q1.OUT"
            and "U1.VM" in pwr03.get("load_endpoints", "")
        ),
        "regulator_input_and_output_are_split": (
            pwr05.get("net_role") == "regulator_input"
            and pwr05.get("regulator_ref") == "U6"
            and pwr05.get("source_endpoints") == "VM_PROTECTED"
            and pwr05.get("load_endpoints") == "U6.IN"
            and pwr06.get("net_role") == "regulator_output"
            and pwr06.get("regulator_ref") == "U6"
            and pwr06.get("source_endpoints") == "U6.OUT"
            and "U6.OUT" not in pwr05.get("source_endpoints", "")
            and "VM_PROTECTED" not in pwr06.get("source_endpoints", "")
            and "U6 input/output cannot be shorted" in pwr05.get("default_or_fail_state", "")
        ),
        "motor_return_is_closed_at_pgnd_star": (
            pwr04.get("net_name") == "GND_MOTOR"
            and pwr04.get("net_role") == "motor_return"
            and "J_PWR.3" in pwr04.get("source_endpoints", "")
            and all(f"U1.PGND{index}" in pwr04.get("load_endpoints", "") for index in range(1, 5))
            and pwr04.get("return_or_reference") == "STAR_GND_01"
        ),
        "logic_supply_and_return_are_explicit": (
            pwr06.get("net_name") == "VCC_LOGIC"
            and "U1.VCC.42" in pwr06.get("load_endpoints", "")
            and pwr06.get("return_or_reference") == "GND_LOGIC"
            and pwr07.get("net_name") == "GND_LOGIC"
            and pwr07.get("source_endpoints") == "STAR_GND_01"
            and pwr07.get("return_or_reference") == "GND_MOTOR"
        ),
        "logic_motor_ground_join_is_single_point": (
            "exactly one" in pwr07.get("allowed_join", "").lower()
            and pwr07.get("source_endpoints") == "STAR_GND_01"
            and "GND_CAN_ISO" in pwr07.get("forbidden_join", "")
        ),
        "isolated_can_regulator_input_output_are_split": (
            pwr09.get("net_name") == "VCC_CAN_ISO_INPUT"
            and pwr09.get("net_role") == "isolated_regulator_input"
            and pwr09.get("regulator_ref") == "U7"
            and pwr09.get("source_endpoints") == "VCC_LOGIC"
            and pwr09.get("load_endpoints") == "U7.PRIMARY_IN"
            and pwr10.get("net_name") == "VCC_CAN_ISO"
            and pwr10.get("net_role") == "isolated_regulator_output"
            and pwr10.get("source_endpoints") == "U7.ISO_OUT"
            and pwr10.get("barrier_id") == "U7"
            and "VCC_LOGIC" not in pwr10.get("source_endpoints", "")
        ),
        "isolated_can_power_and_return_are_explicit": (
            pwr10.get("return_or_reference") == "GND_CAN_ISO"
            and pwr11.get("net_name") == "GND_CAN_ISO"
            and pwr11.get("net_role") == "isolated_return"
            and pwr11.get("source_endpoints") == "U7.ISO_GND"
            and "J_CAN.3" in pwr11.get("load_endpoints", "")
            and pwr11.get("barrier_id") == "U7"
            and "GND_MOTOR" in pwr11.get("forbidden_join", "")
            and "GND_LOGIC" in pwr11.get("forbidden_join", "")
        ),
        "isolated_can_barrier_has_no_local_ground_endpoint": (
            all(
                not (endpoint_tokens(row, "source_endpoints") | endpoint_tokens(row, "load_endpoints"))
                & local_ground_tokens
                for row in isolated_rows
            )
            and local_ground_tokens.isdisjoint(isolated_endpoint_tokens)
        ),
        "source_and_load_endpoints_are_disjoint": endpoint_overlap_free,
        "all_power_rows_remain_candidate_or_concept": all(
            by_id.get(row_id, {}).get("freeze_status", "")
            in {"CONCEPT_TOPOLOGY", "CANDIDATE_POWER_BLOCK", "CANDIDATE_PINOUT"}
            for row_id in required_ids
        ),
    }


def validate_placement_direction(rows: list[dict[str, str]], layout: dict[str, Any]) -> dict[str, bool]:
    """Check that the functional placement honors the declared rear connector datum."""
    by_id = {row.get("block_id", ""): row for row in rows}
    board_height = float(layout["board_height_mm"])
    rear_ids = {"J_SAFE", "J_CAN", "J_ML", "J_MR"}
    rear_rows = [by_id.get(reference, {}) for reference in rear_ids]
    rear_edge = all(
        row
        and row.get("connector_side") == "+Y_REAR"
        and abs(float(row["y_mm"]) + float(row["height_mm"]) / 2 - board_height) <= 0.01
        for row in rear_rows
    )
    return {
        "connector_side_declares_rear_datum": layout.get("connector_side") == "+Y_REAR",
        "rear_connectors_are_present": all(row for row in rear_rows),
        "rear_connectors_face_plus_y_edge": rear_edge,
        "motor_outputs_share_rear_datum": all(
            by_id.get(reference, {}).get("connector_side") == "+Y_REAR" for reference in ("J_ML", "J_MR")
        ),
        "all_placement_blocks_remain_conceptual": all(row.get("freeze_status") == "CONCEPT_ONLY" for row in rows),
    }


def validate_safety_paths(rows: list[dict[str, str]]) -> dict[str, bool]:
    by_id = {row.get("path_id", ""): row for row in rows}
    fault_a = by_id.get("SG-A-FAULT", {})
    fault_b = by_id.get("SG-B-FAULT", {})
    enable_a = by_id.get("SG-A-ENABLE", {})
    enable_b = [by_id.get(f"SG-B-ENABLE-{index}", {}) for index in range(1, 5)]
    return {
        "dual_enable_paths_are_present": (
            enable_a.get("source_net") == "SAFE_ENABLE_A"
            and enable_a.get("guard_component") == "U4"
            and enable_a.get("destination_endpoint") == "U1.25_nSLEEP"
            and all(
                row.get("source_net") == "SAFE_ENABLE_B"
                and row.get("guard_component") == "U5"
                and row.get("destination_endpoint") == f"U1.{29 + index}_EN{index}"
                for index, row in enumerate(enable_b, start=1)
            )
        ),
        "nFAULT_has_two_independent_hardware_inhibits": (
            fault_a.get("source_net") == "DRV_NFAULT"
            and fault_b.get("source_net") == "DRV_NFAULT"
            and fault_a.get("source_endpoint") == "U1.41"
            and fault_b.get("source_endpoint") == "U1.41"
            and fault_a.get("guard_component") == "U4"
            and fault_b.get("guard_component") == "U5"
            and fault_a.get("independent_from") == "B"
            and fault_b.get("independent_from") == "A"
            and fault_a.get("software_dependency") == "no"
            and fault_b.get("software_dependency") == "no"
            and "inhibit" in fault_a.get("default_state", "").lower()
            and "inhibit" in fault_b.get("default_state", "").lower()
            and fault_a.get("fault_integrity_policy") == "open_or_short_inhibits"
            and fault_b.get("fault_integrity_policy") == "open_or_short_inhibits"
        ),
        "nFAULT_reaches_both_driver_gate_domains": (
            fault_a.get("destination_endpoint") == "U1.25_nSLEEP"
            and all(
                endpoint in fault_b.get("destination_endpoint", "")
                for endpoint in ("U1.30_EN1", "U1.31_EN2", "U1.32_EN3", "U1.33_EN4")
            )
        ),
        "safety_returns_are_independent": (
            by_id.get("SG-A-RETURN", {}).get("source_net") == "SAFE_RETURN_A"
            and by_id.get("SG-B-RETURN", {}).get("source_net") == "SAFE_RETURN_B"
            and by_id.get("SG-A-RETURN", {}).get("independent_from") == "B"
            and by_id.get("SG-B-RETURN", {}).get("independent_from") == "A"
        ),
        "power_good_inhibits_both_channels": (
            by_id.get("SG-A-POWER", {}).get("guard_component") == "U4"
            and by_id.get("SG-B-POWER", {}).get("guard_component") == "U5"
            and "inhibit" in by_id.get("SG-A-POWER", {}).get("default_state", "").lower()
            and "inhibit" in by_id.get("SG-B-POWER", {}).get("default_state", "").lower()
        ),
        "every_safety_path_is_hardware_default_inhibit": all(
            "inhibit" in row.get("default_state", "").lower() and row.get("software_dependency") == "no" for row in rows
        ),
    }


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
    net_topology = read_csv("net-topology.csv", package)
    safety_paths = read_csv("safety-gate-connectivity.csv", package)
    verification = read_csv("verification-matrix.csv", package)
    gates = read_csv("release-gates.csv", package)
    placement = read_csv("placement-plan.csv", package)
    layout = spec["layout_concept"]
    pin_numbers = parsed_candidate_pins(pins)
    budget_by_id = {row["parameter_id"]: row for row in budget}
    connector_signals = {row["signal"] for row in connectors}
    connector_references = {row["reference"] for row in connectors}
    release_blockers = [row["gate_id"] for row in gates if row["release_blocker"] == "yes"]
    net_topology_checks = validate_net_topology(net_topology)
    safety_path_checks = validate_safety_paths(safety_paths)
    placement_direction_checks = validate_placement_direction(placement, layout)
    schematic_contract = (package / "schematic-design.md").read_text(encoding="utf-8")
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
        "childboard_connector_coverage_is_explicit": {
            "J_PWR",
            "J_SAFE",
            "J_CAN",
            "J_ML",
            "J_MR",
            "J_ENC_L",
            "J_ENC_R",
        }
        <= connector_references
        and {
            "MOTOR_L_A",
            "MOTOR_L_B",
            "MOTOR_R_A",
            "MOTOR_R_B",
            "ENC_L_VCC",
            "ENC_L_GND",
            "ENC_L_A",
            "ENC_L_B",
            "ENC_R_VCC",
            "ENC_R_GND",
            "ENC_R_A",
            "ENC_R_B",
        }
        <= connector_signals,
        "software_has_no_safety_authority": not spec["safety"]["software_can_assert_safety_permission"]
        and spec["safety"]["either_channel_open_disables_both_axes"]
        and not spec["control"]["drv8962_has_spi"]
        and not spec["control"]["motor_cs_signals_are_usable_as_drv8962_spi"],
        "supply_ground_topology_is_closed": all(net_topology_checks.values()),
        "safety_gate_connectivity_is_fail_closed": all(safety_path_checks.values())
        and spec["safety"]["driver_fault_hardware_inhibit"]
        and spec["safety"]["driver_fault_fanout_channels"] == 2
        and not spec["safety"]["software_can_clear_fault_latch"],
        "schematic_contract_is_explicit_but_not_orderable": all(
            marker in schematic_contract
            for marker in (
                "ARCHITECTURE-ONLY",
                "DO_NOT_ORDER",
                "net-topology.csv",
                "safety-gate-connectivity.csv",
                "STAR_GND_01",
                "GND_CAN_ISO",
                "U1.nFAULT",
                "MTR-SCHEMATIC",
            )
        )
        and spec["controlled_design_files"]["status"] == "CANDIDATE_CONTRACT_ONLY",
        "logic_power_candidates_are_unapproved": {
            (row["reference"], row["candidate_mpn_or_class"], row["selection_status"])
            for row in bom
            if row["reference"] in {"U6", "U7"}
        }
        == {
            ("U6", "TBD_LOGIC_BUCK_12V_TO_5V", "TBD_BLOCKING"),
            ("U7", "TBD_ISOLATED_5V_TO_5V_DC_DC", "TBD_BLOCKING"),
        }
        and {
            (row["reference"], row["candidate"], row["decision"])
            for row in approvals
            if row["reference"] in {"U6", "U7"}
        }
        == {
            ("U6", "TBD_LOGIC_BUCK_12V_TO_5V", "PENDING"),
            ("U7", "TBD_ISOLATED_5V_TO_5V_DC_DC", "PENDING"),
        },
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
        "nFAULT_pin_is_declared_hardware_inhibit_source": "hardware inhibit"
        in next(row for row in pins if row["pin_name"] == "nFAULT")["role"],
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
        "placement_honors_rear_connector_datum": all(placement_direction_checks.values()),
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
            "net_topology_row_count": len(net_topology),
            "safety_path_count": len(safety_paths),
            "nFAULT_hardware_inhibit_path_count": sum(
                row.get("path_id") in {"SG-A-FAULT", "SG-B-FAULT"} for row in safety_paths
            ),
            "logic_power_candidate_count": sum(row["reference"] in {"U6", "U7"} for row in bom),
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
        "net_topology_checks": net_topology_checks,
        "safety_path_checks": safety_path_checks,
        "placement_direction_checks": placement_direction_checks,
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
        "net_topology_checks": report["net_topology_checks"],
        "safety_path_checks": report["safety_path_checks"],
        "placement_direction_checks": report["placement_direction_checks"],
        "metrics": report["metrics"],
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
