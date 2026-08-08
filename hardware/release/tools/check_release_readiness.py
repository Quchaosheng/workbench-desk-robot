"""Cross-check the hardware release register and preserve fail-closed status."""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "hardware" / "release"


def read_rows() -> list[dict[str, str]]:
    with (PACKAGE / "evidence-register.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_report(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def validate() -> dict:
    rows = read_rows()
    statuses = {"PASS", "BLOCKED", "NOT_EXECUTED", "HOLD"}
    report_checks = {
        "gate_ids_are_unique": len(rows) == len({row["gate_id"] for row in rows}),
        "all_gates_have_owner_and_next_action": all(row["owner"] and row["next_action"] for row in rows),
        "statuses_are_controlled": all(row["status"] in statuses for row in rows),
        "evidence_references_exist": all((ROOT / row["evidence_ref"]).exists() for row in rows),
        "all_blockers_are_explicit": all(row["release_blocker"] in {"yes", "no"} for row in rows),
        "blocked_gates_are_not_pass": all(
            row["status"] == "BLOCKED" for row in rows if row["release_blocker"] == "yes"
        ),
        "upstream_reports_remain_fail_closed": (
            load_report("hardware/pcb/generated/release_readiness.json")["status"] == "ORDER_RELEASE_BLOCKED"
            and load_report("hardware/procurement/generated/procurement_report.json")["status"]
            == "ORDER_RELEASE_BLOCKED"
            and load_report("hardware/qa/generated/qa_report.json")["physical_results"] == "NOT_EXECUTED"
            and load_report("hardware/validation/generated/validation_report.json")["physical_results"]
            == "NOT_EXECUTED"
        ),
    }
    blockers = [row["gate_id"] for row in rows if row["release_blocker"] == "yes" and row["status"] != "PASS"]
    report = {
        "package": "hardware-release-readiness",
        "checks": report_checks,
        "pass": all(report_checks.values()),
        "gate_count": len(rows),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "status": "RELEASE_BLOCKED" if blockers else "RELEASE_READY_FOR_SIGNOFF",
        "note": (
            "PASS means repository evidence is present; it never substitutes for "
            "external physical or commercial evidence."
        ),
    }
    output = PACKAGE / "generated" / "release_readiness_report.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = validate()
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["pass"] else 1)
