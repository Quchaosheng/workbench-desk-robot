from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate() -> dict[str, object]:
    with (ROOT / "routing.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    operations = [int(row["op"]) for row in rows]
    minutes = [int(row["target_minutes"]) for row in rows]
    gates = [row["quality_gate"] for row in rows]
    checks = {
        "operations_are_unique_and_ordered": operations == sorted(set(operations)),
        "each_operation_is_5_to_10_minutes": all(5 <= value <= 10 for value in minutes),
        "each_operation_has_unique_quality_gate": len(gates) == len(set(gates)) and all(gates),
        "each_operation_has_record": all(row["required_record"] for row in rows),
        "safety_test_exists": any(row["station"] == "SAFETY_TEST" for row in rows),
    }
    return {
        "operation_count": len(rows),
        "total_touch_minutes": sum(minutes),
        "ideal_units_per_8h_shift": round(480 / max(minutes), 1),
        "checks": checks,
        "pass": all(checks.values()),
    }


def main() -> None:
    report = validate()
    generated = ROOT / "generated"
    generated.mkdir(exist_ok=True)
    (generated / "route_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["pass"]:
        raise SystemExit("manufacturing route validation failed")


if __name__ == "__main__":
    main()
