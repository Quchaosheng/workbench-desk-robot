from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "generated" / "release_readiness.json"
EXPECTED_COPPER_LAYERS = ["F.Cu", *[f"In{index}.Cu" for index in range(1, 7)], "B.Cu"]
ISOLATED_POWER_TBD = "TBD_36_60V_TO_12V_240W_ISOLATED"
ISOLATED_POWER_TBD_LAND_PATTERN = "WB:Isolated_48V_12V_240W_TBD"
ISOLATED_POWER_TBD_FOOTPRINT = "Isolated_48V_12V_240W_TBD"
ISOLATED_POWER_TBD_SYMBOL = "ISOLATED_DC_DC_TBD"
INCOMPATIBLE_ISOLATED_POWER_MARKERS = ("DCM3623", "Vicor_DCM3623")


def read_csv(name: str) -> list[dict[str, str]]:
    with (ROOT / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def check_isolated_power_tbd_guard(
    component_matrix: list[dict[str, str]],
    approval_register: list[dict[str, str]],
    bom: list[dict[str, str]],
    artifact_texts: dict[str, str],
) -> dict[str, object]:
    matrix_rows = [row for row in component_matrix if row["reference"] == "U2"]
    approval_rows = [row for row in approval_register if row["reference"] == "U2"]
    bom_rows = [row for row in bom if row["reference"] == "U2"]
    matrix_uses_tbd = len(matrix_rows) == 1 and matrix_rows[0]["primary_candidate"] == ISOLATED_POWER_TBD
    approval_uses_tbd = len(approval_rows) == 1 and approval_rows[0]["candidate"] == ISOLATED_POWER_TBD
    bom_uses_tbd = (
        len(bom_rows) == 1
        and bom_rows[0]["design_candidate"] == ISOLATED_POWER_TBD
        and bom_rows[0]["package_or_module"] == ISOLATED_POWER_TBD_LAND_PATTERN
    )
    incompatible_occurrences = {
        name: [marker for marker in INCOMPATIBLE_ISOLATED_POWER_MARKERS if marker in text]
        for name, text in artifact_texts.items()
    }
    incompatible_occurrences = {name: markers for name, markers in incompatible_occurrences.items() if markers}
    required_artifact_markers = {
        "design_data.py": [ISOLATED_POWER_TBD, ISOLATED_POWER_TBD_FOOTPRINT, ISOLATED_POWER_TBD_SYMBOL],
        "controller.kicad_pcb": [ISOLATED_POWER_TBD_FOOTPRINT, "U2 LAND PATTERN TBD", "DO NOT FIT"],
        "controller.kicad_sch": [ISOLATED_POWER_TBD, ISOLATED_POWER_TBD_FOOTPRINT, ISOLATED_POWER_TBD_SYMBOL],
        "controller.kicad_sym": [ISOLATED_POWER_TBD_SYMBOL],
        "controller.ses": [ISOLATED_POWER_TBD_FOOTPRINT],
        "controller.net": [ISOLATED_POWER_TBD, ISOLATED_POWER_TBD_FOOTPRINT],
        "fabrication/positions.csv": [ISOLATED_POWER_TBD_FOOTPRINT],
        "WB.pretty": [ISOLATED_POWER_TBD_FOOTPRINT],
    }
    missing_placeholder_markers = {
        name: [marker for marker in markers if marker not in artifact_texts.get(name, "")]
        for name, markers in required_artifact_markers.items()
    }
    missing_placeholder_markers = {name: markers for name, markers in missing_placeholder_markers.items() if markers}
    passed = (
        matrix_uses_tbd
        and approval_uses_tbd
        and bom_uses_tbd
        and not incompatible_occurrences
        and not missing_placeholder_markers
    )
    return {
        "pass": passed,
        "required_placeholder": ISOLATED_POWER_TBD,
        "required_land_pattern_placeholder": ISOLATED_POWER_TBD_LAND_PATTERN,
        "component_matrix_uses_tbd": matrix_uses_tbd,
        "approval_register_uses_tbd": approval_uses_tbd,
        "fabrication_bom_uses_tbd": bom_uses_tbd,
        "incompatible_markers": list(INCOMPATIBLE_ISOLATED_POWER_MARKERS),
        "incompatible_occurrences": incompatible_occurrences,
        "missing_placeholder_markers": missing_placeholder_markers,
        "note": (
            "The former DCM3623 selection is excluded. U2 remains a requirement envelope until an orderable "
            "36-60 V to regulated 12 V isolated 240 W-class MPN and its land pattern are frozen by ECO."
        ),
    }


def audit() -> dict[str, object]:
    pinout = read_csv("connector-pinout.csv")
    component_matrix = read_csv("component-selection-matrix.csv")
    approval_register = read_csv("component-approval-register.csv")
    testpoint_coverage = read_csv("testpoint-coverage.csv")
    bom = read_csv("fabrication/bom.csv")
    schematic = (ROOT / "kicad/controller.kicad_sch").read_text(encoding="utf-8")
    board = (ROOT / "kicad/controller.kicad_pcb").read_text(encoding="utf-8")
    design_data = (ROOT / "tools/design_data.py").read_text(encoding="utf-8")
    bom_text = (ROOT / "fabrication/bom.csv").read_text(encoding="utf-8")
    symbol_library = (ROOT / "kicad/controller.kicad_sym").read_text(encoding="utf-8")
    routing_session = (ROOT / "kicad/controller.ses").read_text(encoding="utf-8")
    netlist = (ROOT / "generated/controller.net").read_text(encoding="utf-8")
    positions = (ROOT / "fabrication/positions.csv").read_text(encoding="utf-8")
    footprint_paths = sorted((ROOT / "kicad/WB.pretty").glob("*.kicad_mod"))
    footprint_library = "\n".join(f"{path.name}\n{path.read_text(encoding='utf-8')}" for path in footprint_paths)
    custom_rules = (ROOT / "kicad/controller.kicad_dru").read_text(encoding="utf-8")
    fabrication_notes = (ROOT / "fabrication/fabrication-notes.csv").read_text(encoding="utf-8")
    gerber_job = json.loads((ROOT / "fabrication/gerbers/controller-job.gbrjob").read_text(encoding="utf-8"))
    drc = (ROOT / "generated/drc.rpt").read_text(encoding="utf-8")
    erc = (ROOT / "generated/erc.rpt").read_text(encoding="utf-8")
    bringup = (ROOT / "fabrication/bringup-test-plan.csv").read_text(encoding="utf-8")
    stackup_rows = read_csv("fabrication/stackup.csv")
    safety_truth_table = read_csv("safety-gate-truth-table.csv")
    harness_report = json.loads(
        (ROOT.parent / "manufacturing/generated/harness_report.json").read_text(encoding="utf-8")
    )
    connectivity_report = json.loads((ROOT / "generated/connectivity_report.json").read_text(encoding="utf-8"))
    layout_report = json.loads((ROOT / "generated/layout_report.json").read_text(encoding="utf-8"))

    board_layers = [
        match.group(1) for match in re.finditer(r'^\s*\(\d+ "((?:F|B|In\d+)\.Cu)" signal\)$', board, flags=re.MULTILINE)
    ]
    stackup_layers = [row["layer"] for row in stackup_rows]
    stackup_text = "\n".join(",".join(row.values()) for row in stackup_rows)

    pin_counts = {
        reference: len([row for row in pinout if row["reference"] == reference])
        for reference in {row["reference"] for row in pinout}
    }
    duplicate_pins = len({(row["reference"], row["pin"]) for row in pinout}) != len(pinout)
    required_populated = {"J1", "J2", "J3", "J4", "J5", "J6", "J10", "J11", "J12"}
    procurement_holds = [row["reference"] for row in bom if row["procurement_gate"] != "APPROVED"]
    bom_references = {reference for row in bom for reference in row["reference"].split()}
    board_references = set(re.findall(r'\(property "Reference" "([^"]+)"', board))
    approved = [
        row
        for row in approval_register
        if row["decision"] == "APPROVED"
        and row["approved_mpn"]
        and row["datasheet_revision"]
        and row["approved_by"]
        and row["approved_at"]
        and row["evidence_ref"]
    ]
    isolated_power_guard = check_isolated_power_tbd_guard(
        component_matrix,
        approval_register,
        bom,
        {
            "design_data.py": design_data,
            "fabrication/bom.csv": bom_text,
            "controller.kicad_pcb": board,
            "controller.kicad_sch": schematic,
            "controller.kicad_sym": symbol_library,
            "controller.ses": routing_session,
            "controller.net": netlist,
            "fabrication/positions.csv": positions,
            "WB.pretty": footprint_library,
        },
    )

    engineering_checks = {
        "drc_clean": "Found 0 DRC violations" in drc and "Found 0 unconnected pads" in drc,
        "erc_clean": "0  Errors 0  Warnings" in erc,
        "controlled_pinout_complete": pin_counts.get("J4") == 20
        and required_populated <= set(pin_counts)
        and pin_counts.get("J2") == 4
        and pin_counts.get("J5") == 4
        and pin_counts.get("J6") == 4
        and pin_counts.get("J10") == 4
        and pin_counts.get("J11") == 4
        and pin_counts.get("J12") == 4
        and not duplicate_pins,
        "jetson_test_plan_uses_12v": "Jetson protected 12V branch" in bringup and "5V rail" not in bringup,
        "stackup_matches_current_rails": "protected Jetson 12V" in stackup_text
        and "5V Jetson power" not in stackup_text,
        "eight_copper_layers_declared": board_layers == EXPECTED_COPPER_LAYERS
        and stackup_layers == EXPECTED_COPPER_LAYERS,
        "primary_secondary_8mm_clearance_rule_declared": "constraint clearance (min 8mm)" in custom_rules
        and "VBAT_PROTECTED" in custom_rules
        and "GND_PWR" in custom_rules,
        "software_enable_is_not_safety_output": "MOTOR_ENABLE_REQ" in board and "MOTOR_ENABLE_SAFE" in board,
        "safety_truth_table_covers_channel_discrepancy": any(
            row["channel_a_closed"] != row["channel_b_closed"] and row["motor_enable_safe"] == "0"
            for row in safety_truth_table
        ),
        "harness_engineering_pass": harness_report["engineering_package_pass"],
        "component_matrix_covers_all_active_modules": {row["reference"] for row in component_matrix}
        >= {"U1", "U2", "U3", "U4", "U5", "U6", "U7", "U8"},
        "bom_covers_all_board_components": bom_references == board_references,
        "approval_register_covers_all_pending_bom_lines": {row["reference"] for row in approval_register}
        == set(procurement_holds)
        and all(row["candidate"] and row["required_approver"] for row in approval_register),
        "board_connectivity_audit_pass": connectivity_report["pass"],
        "board_layout_hard_gates_pass": layout_report["hard_gate_pass"],
        "eight_testpoints_have_measurement_coverage": len(testpoint_coverage) == 8
        and {row["reference"] for row in testpoint_coverage} == {f"TP{index}" for index in range(1, 9)},
        "fabrication_metadata_controlled": '(rev "EVT1")' in board
        and '(copper_finish "ENIG")' in board
        and gerber_job["GeneralSpecs"]["ProjectId"]["Revision"] == "EVT1"
        and gerber_job["GeneralSpecs"]["Finish"] == "ENIG"
        and "FAB-003" in fabrication_notes,
    }
    order_release_checks = {
        "detailed_schematic_has_symbols": schematic.count("(symbol (lib_id") >= 100
        and schematic.count("(wire ") >= 300,
        "all_bom_lines_approved": len(approved) == len(approval_register),
        "physical_bringup_evidence_attached": False,
        "safety_analysis_approved": False,
        "supplier_dfm_closed": False,
        "harness_release_checks_closed": all(harness_report["release_checks"].values()),
        "component_mpn_and_avl_closed": all(row["procurement_status"] == "APPROVED" for row in component_matrix),
        "isolated_power_excluded_part_absent_and_tbd_placeholders_consistent": isolated_power_guard["pass"],
        "isolated_power_mpn_and_land_pattern_frozen": False,
    }
    return {
        "status": "ORDER_RELEASE_BLOCKED" if not all(order_release_checks.values()) else "ORDER_RELEASED",
        "engineering_package_pass": all(engineering_checks.values()),
        "engineering_checks": engineering_checks,
        "order_release_checks": order_release_checks,
        "procurement_hold_references": [row["reference"] for row in approval_register if row not in approved],
        "blocker_count": sum(not value for value in order_release_checks.values()),
        "component_counts": {
            "board_footprints": len(board_references),
            "bom_references": len(bom_references),
        },
        "layout_status": {
            "status": layout_report["status"],
            "open_risks": layout_report["warnings"],
        },
        "isolated_power_guard": isolated_power_guard,
        "copper_layers": {
            "expected": EXPECTED_COPPER_LAYERS,
            "board": board_layers,
            "stackup": stackup_layers,
        },
        "note": (
            "The checked-in schematic is component-level and its ERC is clean. U2 is not selected, and any stale "
            "excluded-part data fails the engineering guard until an ECO replaces the schematic, "
            "BOM, footprint, placement, routing and thermal model. PENDING approval rows still require signed "
            "owner evidence; this audit cannot approve components or infer physical validation."
        ),
    }


def main() -> None:
    report = audit()
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["engineering_package_pass"]:
        raise SystemExit("engineering package readiness audit failed")


if __name__ == "__main__":
    main()
