"""Validate the procurement package without inventing commercial evidence."""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "hardware" / "procurement"


def read_csv(name: str) -> list[dict[str, str]]:
    with (PACKAGE / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def validate() -> dict:
    bom = read_csv("bom.csv")
    quotes = read_csv("quote-register.csv")
    scorecard = read_csv("supplier-scorecard.csv")
    checklist = read_csv("po-checklist.csv")
    ids = {row["item_id"] for row in bom}
    quote_counts = {item: sum(row["item_id"] == item for row in quotes) for item in ids}
    critical = {row["item_id"] for row in bom if row["category"] in {"power", "isolation", "pcb"}}
    checks = {
        "bom_has_unique_ids": len(ids) == len(bom) and bool(bom),
        "all_bom_rows_have_owner_and_source": all(row["owner"] and row["source"] for row in bom),
        "critical_items_have_two_quote_channels": all(quote_counts[item] >= 2 for item in critical),
        "no_unquoted_price_is_present": all(not row["unit_cost_usd"] for row in bom if row["quote_status"] != "QUOTED"),
        "scorecard_totals_are_reproducible": all(
            float(row["total_score"])
            == sum(
                float(row[key])
                for key in ("quality_score_0_5", "lead_time_score_0_5", "cost_score_0_5", "technical_score_0_5")
            )
            for row in scorecard
        ),
        "po_checklist_has_stop_gates": any(row["stop_if_missing"] == "yes" for row in checklist),
    }
    report = {
        "package": "procurement",
        "checks": checks,
        "pass": all(checks.values()),
        "bom_line_count": len(bom),
        "quote_request_count": len(quotes),
        "supplier_count": len(scorecard),
        "status": "ORDER_RELEASE_BLOCKED",
        "blocked_by": ["dated supplier quotes", "AVL approval", "incoming inspection evidence"],
    }
    output = PACKAGE / "generated" / "procurement_report.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = validate()
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["pass"] else 1)
