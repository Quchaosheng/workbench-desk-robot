from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REGISTER = ROOT / "hardware/release/hardware-optimization-register.csv"
REQUIRED_FIELDS = {
    "optimization_id",
    "domain",
    "priority",
    "owner",
    "current_state",
    "optimization_action",
    "acceptance_evidence",
    "stage",
    "status",
}
DOMAINS = {
    "power",
    "thermal",
    "emc",
    "safety",
    "validation",
    "harness",
    "mechanical",
    "manufacturing",
    "procurement",
    "release",
}
PRIORITIES = {"P0", "P1", "P2"}
STAGES = {"EVT", "PRODUCTION"}
STATUSES = {"OPEN", "IN_PROGRESS", "CLOSED"}


def validate(rows: list[dict[str, str]]) -> dict[str, object]:
    ids = [row.get("optimization_id", "") for row in rows]
    checks = {
        "rows_present": bool(rows),
        "required_fields_present": bool(rows) and all(REQUIRED_FIELDS <= set(row) for row in rows),
        "ids_unique_and_nonempty": len(ids) == len(set(ids)) and all(ids),
        "domains_controlled": all(row.get("domain") in DOMAINS for row in rows),
        "priorities_controlled": all(row.get("priority") in PRIORITIES for row in rows),
        "stages_controlled": all(row.get("stage") in STAGES for row in rows),
        "statuses_controlled": all(row.get("status") in STATUSES for row in rows),
        "owners_and_actions_present": all(
            row.get("owner", "").strip()
            and row.get("current_state", "").strip()
            and row.get("optimization_action", "").strip()
            and row.get("acceptance_evidence", "").strip()
            for row in rows
        ),
        "required_domains_covered": {row.get("domain") for row in rows} >= DOMAINS,
        "p0_items_are_open_or_in_progress": all(
            row.get("status") in {"OPEN", "IN_PROGRESS"} for row in rows if row.get("priority") == "P0"
        ),
    }
    return {
        "package": "hardware-optimization-register",
        "row_count": len(rows),
        "checks": checks,
        "pass": all(checks.values()),
        "open_p0": [row["optimization_id"] for row in rows if row["priority"] == "P0" and row["status"] != "CLOSED"],
        "open_count": sum(row.get("status") != "CLOSED" for row in rows),
    }


def main() -> int:
    with REGISTER.open(newline="", encoding="utf-8") as handle:
        report = validate(list(csv.DictReader(handle)))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
