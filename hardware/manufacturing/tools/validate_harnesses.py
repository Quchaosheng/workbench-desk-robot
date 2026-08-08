from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "harness-spec.csv"
OUT = ROOT / "generated/harness_report.json"
COPPER_RESISTIVITY_OHM_MM2_PER_M = 0.0175


def validate() -> dict[str, object]:
    with SPEC.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    results = []
    for row in rows:
        length_m = float(row["length_m"])
        voltage_v = float(row["voltage_v"])
        current_a = float(row["max_current_a"])
        area_mm2 = float(row["copper_area_mm2"])
        supply_count = int(row["parallel_supply"])
        return_count = int(row["parallel_return"])
        supply_resistance = COPPER_RESISTIVITY_OHM_MM2_PER_M * length_m / (area_mm2 * supply_count)
        return_resistance = COPPER_RESISTIVITY_OHM_MM2_PER_M * length_m / (area_mm2 * return_count)
        voltage_drop_v = current_a * (supply_resistance + return_resistance)
        drop_percent = voltage_drop_v / voltage_v * 100
        current_density = current_a / (area_mm2 * min(supply_count, return_count))
        results.append(
            {
                "harness_id": row["harness_id"],
                "voltage_drop_v": round(voltage_drop_v, 3),
                "voltage_drop_percent": round(drop_percent, 2),
                "current_density_a_per_mm2": round(current_density, 2),
                "drop_pass": drop_percent <= 3.0,
                "current_density_pass": current_density <= 6.0,
                "bend_radius_pass": float(row["min_bend_radius_mm"]) <= 20,
                "shield_required_and_defined": row["harness_id"] not in {"H04", "H05", "H06", "H07", "H08"}
                or row["shield"] != "no",
            }
        )

    engineering_checks = {
        "eight_controlled_harnesses": len(rows) == 8,
        "unique_harness_ids": len({row["harness_id"] for row in rows}) == len(rows),
        "all_voltage_drops_within_3_percent": all(item["drop_pass"] for item in results),
        "all_current_density_within_6a_per_mm2": all(item["current_density_pass"] for item in results),
        "all_bend_radii_fit_20mm_service_margin": all(item["bend_radius_pass"] for item in results),
        "signal_and_safety_harness_shields_defined": all(item["shield_required_and_defined"] for item in results),
    }
    release_checks = {
        "all_mating_parts_approved": all(row["mating_part_status"] == "APPROVED" for row in rows),
        "physical_continuity_and_pull_test_attached": False,
        "installed_length_and_chafe_check_attached": False,
    }
    return {
        "status": "HARNESS_RELEASE_BLOCKED" if not all(release_checks.values()) else "HARNESS_RELEASED",
        "engineering_package_pass": all(engineering_checks.values()),
        "engineering_checks": engineering_checks,
        "release_checks": release_checks,
        "results": results,
    }


def main() -> None:
    report = validate()
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["engineering_package_pass"]:
        raise SystemExit("harness engineering checks failed")


if __name__ == "__main__":
    main()
