"""Validate quality plans and keep physical results explicitly unexecuted."""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "hardware" / "qa"


def rows(name: str) -> list[dict[str, str]]:
    with (PACKAGE / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def validate() -> dict:
    inspection = rows("inspection-plan.csv")
    fmea = rows("fmea.csv")
    aql = rows("aql-plan.csv")
    compliance = rows("compliance-matrix.csv")
    checks = {
        "inspection_plan_is_complete": len(inspection) >= 10
        and all(row["method"] and row["evidence"] for row in inspection),
        "inspection_rows_have_explicit_status": all(
            row["status"] in {"NOT_EXECUTED", "PASS", "FAIL", "HOLD"} for row in inspection
        ),
        "fmea_rpn_is_reproducible": all(
            int(row["rpn"]) == int(row["severity_1_10"]) * int(row["occurrence_1_10"]) * int(row["detection_1_10"])
            for row in fmea
        ),
        "fmea_has_safety_failure_modes": any(row["severity_1_10"] == "10" for row in fmea),
        "aql_has_zero_tolerance_safety_rule": all("zero tolerance" in row["safety_rule"] for row in aql),
        "compliance_does_not_claim_certification": all(
            row["status"] not in {"CERTIFIED", "PASSED"} for row in compliance
        ),
    }
    report = {
        "package": "qa",
        "checks": checks,
        "pass": all(checks.values()),
        "inspection_count": len(inspection),
        "fmea_count": len(fmea),
        "compliance_count": len(compliance),
        "status": "EXECUTION_REQUIRED",
        "physical_results": "NOT_EXECUTED",
    }
    output = PACKAGE / "generated" / "qa_report.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = validate()
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["pass"] else 1)
