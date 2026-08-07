from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "generated" / "release_readiness.json"


def read_csv(name: str) -> list[dict[str, str]]:
    with (ROOT / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def audit() -> dict[str, object]:
    pinout = read_csv("connector-pinout.csv")
    bom = read_csv("fabrication/bom.csv")
    schematic = (ROOT / "kicad/controller.kicad_sch").read_text(encoding="utf-8")
    board = (ROOT / "kicad/controller.kicad_pcb").read_text(encoding="utf-8")
    drc = (ROOT / "generated/drc.rpt").read_text(encoding="utf-8")
    erc = (ROOT / "generated/erc.rpt").read_text(encoding="utf-8")
    bringup = (ROOT / "fabrication/bringup-test-plan.csv").read_text(encoding="utf-8")
    stackup = (ROOT / "fabrication/stackup.csv").read_text(encoding="utf-8")
    safety_truth_table = read_csv("safety-gate-truth-table.csv")
    harness_report = json.loads(
        (ROOT.parent / "manufacturing/generated/harness_report.json").read_text(encoding="utf-8")
    )

    pin_counts = {
        reference: len([row for row in pinout if row["reference"] == reference])
        for reference in {row["reference"] for row in pinout}
    }
    duplicate_pins = len({(row["reference"], row["pin"]) for row in pinout}) != len(pinout)
    procurement_holds = [row["reference"] for row in bom if row["procurement_gate"] != "APPROVED"]

    engineering_checks = {
        "drc_clean": "Found 0 DRC violations" in drc and "Found 0 unconnected pads" in drc,
        "erc_clean": "0  Errors 0  Warnings" in erc,
        "controlled_pinout_complete": pin_counts.get("J4") == 20
        and pin_counts.get("J10") == 4
        and pin_counts.get("J11") == 4
        and not duplicate_pins,
        "jetson_test_plan_uses_12v": "Jetson protected 12V branch" in bringup and "5V rail" not in bringup,
        "stackup_matches_current_rails": "protected Jetson 12V" in stackup and "5V Jetson power" not in stackup,
        "software_enable_is_not_safety_output": "MOTOR_ENABLE_REQ" in board and "MOTOR_ENABLE_SAFE" in board,
        "safety_truth_table_covers_channel_discrepancy": any(
            row["channel_a_closed"] != row["channel_b_closed"] and row["motor_enable_safe"] == "0"
            for row in safety_truth_table
        ),
        "harness_engineering_pass": harness_report["engineering_package_pass"],
    }
    order_release_checks = {
        "detailed_schematic_has_symbols": "(symbol " in schematic,
        "all_bom_lines_approved": not procurement_holds,
        "physical_bringup_evidence_attached": False,
        "safety_analysis_approved": False,
        "supplier_dfm_closed": False,
        "harness_release_checks_closed": all(harness_report["release_checks"].values()),
    }
    return {
        "status": "ORDER_RELEASE_BLOCKED" if not all(order_release_checks.values()) else "ORDER_RELEASED",
        "engineering_package_pass": all(engineering_checks.values()),
        "engineering_checks": engineering_checks,
        "order_release_checks": order_release_checks,
        "procurement_hold_references": procurement_holds,
        "blocker_count": sum(not value for value in order_release_checks.values()),
        "note": "Clean ERC on the architecture sheet is not evidence of a detailed component-level schematic.",
    }


def main() -> None:
    report = audit()
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["engineering_package_pass"]:
        raise SystemExit("engineering package readiness audit failed")


if __name__ == "__main__":
    main()
