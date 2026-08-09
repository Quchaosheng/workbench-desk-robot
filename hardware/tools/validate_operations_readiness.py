from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "hardware/operations-readiness.json"
OUTPUT = ROOT / "hardware/generated/operations_readiness_report.json"


def read_csv(relative: str) -> list[dict[str, str]]:
    with (ROOT / relative).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def validate() -> dict[str, object]:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    required_files = [
        "hardware/power/README.md",
        "hardware/power/bms-state-machine.csv",
        "hardware/power/protection-thresholds.csv",
        "hardware/mechanical/system-integration.md",
        "hardware/mechanical/mass-ledger.csv",
        "hardware/mechanical/interference-checklist.csv",
        "hardware/procurement/planning-baseline.md",
        "hardware/procurement/planning-bom.csv",
        "hardware/procurement/supplier-scorecard-planning.csv",
        "hardware/manufacturing/production-line.md",
        "hardware/manufacturing/station-map.csv",
        "hardware/manufacturing/fixture-budget.csv",
        "hardware/qa/reliability-gates.md",
        "hardware/qa/fmea-action-register.csv",
        "hardware/qa/early-failure-log.csv",
        "hardware/compliance/README.md",
        "hardware/compliance/evidence-matrix.csv",
        "hardware/support/README.md",
        "hardware/support/case-template.csv",
        "hardware/support/escalation-matrix.csv",
        "docs/user-guide/index.md",
        "docs/user-guide/demo-runbook.md",
        "docs/api.md",
        "mkdocs.yml",
    ]
    checks = {
        "all_package_files_exist": all((ROOT / path).is_file() for path in required_files),
        "power_is_48v_with_three_levels": baseline["power"]
        == {"nominal_pack_voltage_v": 48, "protection_levels": 3, "bms_fail_closed": True},
        "mechanical_design_case_is_55kg": baseline["mechanical"]["design_case_mass_kg"] == 55,
        "planning_bom_is_5100_usd": baseline["procurement"]["planning_bom_usd"] == 5100,
        "certificates_block_po": baseline["procurement"]["critical_certificates_required_before_po"],
        "line_has_six_stations": baseline["manufacturing"]["station_count"] == 6,
        "fixture_budget_is_4000_usd": baseline["manufacturing"]["fixture_budget_usd"] == 4000,
        "minimum_fpy_is_85_percent": baseline["manufacturing"]["minimum_fpy_percent"] >= 85,
        "rpn_actions_start_above_100": baseline["quality"]["rpn_action_threshold"] == 100,
        "early_failure_limit_is_5_percent": baseline["quality"]["maximum_early_failure_percent"] <= 5,
        "demo_route_is_90_minutes": baseline["documentation"]["demo_route_minutes"] == 90,
        "required_compliance_programs_are_present": set(baseline["compliance"]["required_programs"])
        == {"CE", "FCC", "UN38.3"},
        "certification_is_not_claimed": baseline["compliance"]["certification_claim"] == "NOT_CERTIFIED",
        "external_evidence_remains_required": baseline["status"] == "EXTERNAL_EVIDENCE_REQUIRED",
        "bms_has_fail_closed_states": {row["state"] for row in read_csv("hardware/power/bms-state-machine.csv")}
        >= {"OFF", "SELF_TEST", "PRECHARGE", "RUN", "FAULT_LATCHED", "SERVICE"},
        "all_protection_levels_are_defined": {
            row["level"] for row in read_csv("hardware/power/protection-thresholds.csv")
        }
        == {"L1", "L2", "L3"},
        "mass_ledger_sums_to_55kg": abs(
            sum(float(row["mass_kg"]) for row in read_csv("hardware/mechanical/mass-ledger.csv")) - 55
        )
        < 1e-9,
        "mass_ledger_has_physical_validation_status": all(
            row["status"] == "ESTIMATE" for row in read_csv("hardware/mechanical/mass-ledger.csv")
        ),
        "planning_bom_rows_sum_to_5100": sum(
            float(row["extended_cost_usd"]) for row in read_csv("hardware/procurement/planning-bom.csv")
        )
        == 5100,
        "planning_bom_has_certificate_gate": all(
            row["certificate_gate"] == "REQUIRED_BEFORE_PO" for row in read_csv("hardware/procurement/planning-bom.csv")
        ),
        "station_map_has_six_unique_stations": len(
            {row["station"] for row in read_csv("hardware/manufacturing/station-map.csv")}
        )
        == 6,
        "fixture_budget_rows_sum_to_4000": sum(
            float(row["planned_cost_usd"])
            for row in read_csv("hardware/manufacturing/fixture-budget.csv")
            if row["fixture_id"] != "TOTAL"
        )
        == 4000,
        "all_fmea_actions_are_above_rpn_threshold": all(
            int(row["current_rpn"]) > baseline["quality"]["rpn_action_threshold"]
            for row in read_csv("hardware/qa/fmea-action-register.csv")
        ),
        "early_failure_template_is_not_executed": all(
            row["status"] == "NOT_EXECUTED" for row in read_csv("hardware/qa/early-failure-log.csv")
        ),
        "compliance_matrix_has_three_required_programs": {
            row["program"] for row in read_csv("hardware/compliance/evidence-matrix.csv")
        }
        >= {"CE", "FCC", "UN38.3"},
        "compliance_rows_stop_po": all(
            row["po_gate"] == "STOP" for row in read_csv("hardware/compliance/evidence-matrix.csv")
        ),
        "support_has_four_severity_levels": {
            row["severity"] for row in read_csv("hardware/support/escalation-matrix.csv")
        }
        == {"S0", "S1", "S2", "S3"},
    }
    report: dict[str, object] = {
        "package": baseline["package"],
        "pass": all(checks.values()),
        "status": baseline["status"],
        "checks": checks,
        "required_files": required_files,
        "note": "A passing document check never substitutes for quotes, certificates, pilot data, or physical tests.",
    }
    return report


def main() -> None:
    report = validate()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()
