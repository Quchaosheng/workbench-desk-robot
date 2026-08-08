"""Validate field-validation templates and reject fabricated results."""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "hardware" / "validation"


def rows(name: str) -> list[dict[str, str]]:
    with (PACKAGE / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def validate() -> dict:
    matrix = rows("sim2real-matrix.csv")
    faults = rows("fault-scenarios.csv")
    units = rows("first-batch-acceptance.csv")
    statuses = {"NOT_EXECUTED", "PASS", "FAIL", "HOLD"}
    checks = {
        "sim2real_matrix_has_required_dimensions": {row["dimension"] for row in matrix}
        >= {"response_time", "position_accuracy", "grasp_success", "thermal rise"},
        "fault_library_has_twenty_scenarios": len(faults) == 20 and len({row["scenario_id"] for row in faults}) == 20,
        "faults_have_recovery_and_evidence": all(row["recovery_or_safe_state"] and row["evidence"] for row in faults),
        "first_batch_has_ten_units": len(units) == 10 and all(row["unit_id"] for row in units),
        "results_are_explicitly_statused": all(row["status"] in statuses for row in units + faults + matrix),
        "template_does_not_claim_builds": all(row["final_result"] == "NOT_BUILT" for row in units),
    }
    report = {
        "package": "validation",
        "checks": checks,
        "pass": all(checks.values()),
        "sim2real_dimension_count": len(matrix),
        "fault_scenario_count": len(faults),
        "first_batch_unit_count": len(units),
        "status": "PHYSICAL_EXECUTION_REQUIRED",
        "physical_results": "NOT_EXECUTED",
    }
    output = PACKAGE / "generated" / "validation_report.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = validate()
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["pass"] else 1)
