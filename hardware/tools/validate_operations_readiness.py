from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "hardware/operations-readiness.json"
OUTPUT = ROOT / "hardware/generated/operations_readiness_report.json"


def validate() -> dict[str, object]:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    required_files = [
        "hardware/power/README.md",
        "hardware/mechanical/system-integration.md",
        "hardware/procurement/planning-baseline.md",
        "hardware/manufacturing/production-line.md",
        "hardware/qa/reliability-gates.md",
        "hardware/compliance/README.md",
        "hardware/support/README.md",
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
