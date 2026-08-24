from __future__ import annotations

import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
SPEC = json.loads((ROOT / "service-robot-product-baseline.json").read_text(encoding="utf-8"))
INDUSTRIAL_DESIGN = json.loads((ROOT / "service-robot-industrial-design.json").read_text(encoding="utf-8"))


def write_concept_svg() -> None:
    palette = INDUSTRIAL_DESIGN["palette"]
    white = palette["primary_cover"]["hex"]
    graphite = palette["structural_base"]["hex"]
    status = palette["status_light"]["hex"]
    safety = palette["safety_red"]["hex"]
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="760" viewBox="0 0 1200 760">
<rect width="1200" height="760" fill="#E7E9E8"/>
<style>text{{font-family:Arial,sans-serif;fill:#292D32;letter-spacing:0}}.label{{font-size:18px}}.note{{font-size:14px;fill:#596168}}.outline{{stroke:#292D32;stroke-width:4;stroke-linejoin:round}}</style>
<text x="60" y="54" font-size="28" font-weight="700">SERVICE ROBOT REV A - INDUSTRIAL DESIGN CONCEPT</text>
<text x="60" y="82" class="note">
  ORIGINAL FUNCTIONAL CONCEPT - NOT PRODUCTION CAD - SUPPLIER SURFACING AND PHYSICAL VALIDATION REQUIRED
</text>
<g transform="translate(90,115)">
  <text x="170" y="0" class="label" font-weight="700">FRONT</text>
  <rect x="95" y="475" width="330" height="150" rx="40" fill="{white}" class="outline"/>
  <rect x="95" y="565" width="330" height="60" rx="26" fill="{graphite}"/>
  <circle cx="125" cy="555" r="7" fill="#202428"/><circle cx="395" cy="555" r="7" fill="#202428"/>
  <rect x="180" y="170" width="160" height="340" rx="35" fill="{white}" class="outline"/>
  <rect x="152" y="105" width="216" height="105" rx="28" fill="{white}" class="outline"/>
  <rect x="188" y="128" width="144" height="54" rx="8" fill="#1E252B"/>
  <circle cx="260" cy="121" r="7" fill="{status}"/>
  <path d="M180 225 L105 250 L48 335" fill="none" stroke="{graphite}" stroke-width="34" stroke-linecap="round"/>
  <path d="M340 225 L415 250 L472 335" fill="none" stroke="{graphite}" stroke-width="34" stroke-linecap="round"/>
  <circle cx="105" cy="250" r="21" fill="{white}" class="outline"/>
  <circle cx="415" cy="250" r="21" fill="{white}" class="outline"/>
  <circle cx="48" cy="335" r="18" fill="{white}" class="outline"/>
  <circle cx="472" cy="335" r="18" fill="{white}" class="outline"/>
  <rect x="220" y="485" width="80" height="18" rx="9" fill="#151A1E"/><circle cx="260" cy="494" r="5" fill="{status}"/>
  <circle cx="190" cy="205" r="10" fill="{safety}"/><circle cx="330" cy="205" r="10" fill="{safety}"/>
</g>
<g transform="translate(665,115)">
  <text x="155" y="0" class="label" font-weight="700">SIDE</text>
  <rect x="55" y="475" width="390" height="150" rx="40" fill="{white}" class="outline"/>
  <rect x="55" y="565" width="390" height="60" rx="26" fill="{graphite}"/>
  <circle cx="115" cy="615" r="35" fill="#171B1F"/><circle cx="385" cy="615" r="35" fill="#171B1F"/>
  <rect x="185" y="170" width="145" height="340" rx="35" fill="{white}" class="outline"/>
  <path d="M192 185 L345 185 L365 112 L205 112 Z" fill="{white}" class="outline"/>
  <rect x="245" y="132" width="105" height="50" rx="7" fill="#1E252B"/>
  <path d="M235 230 L355 265 L425 350" fill="none" stroke="{graphite}" stroke-width="34" stroke-linecap="round"/>
  <circle cx="355" cy="265" r="21" fill="{white}" class="outline"/>
  <circle cx="425" cy="350" r="18" fill="{white}" class="outline"/>
  <rect x="70" y="490" width="65" height="18" rx="9" fill="#151A1E"/>
  <path d="M330 230 L365 230 L365 470 L330 470" fill="none" stroke="#596168" stroke-width="8"/>
  <text x="270" y="455" class="note">rear service spine</text>
</g>
<text x="60" y="728" class="note">
  Warm-white replaceable covers / graphite impact base / functional cyan status light / red reserved for emergency stop
</text>
</svg>'''
    output = ROOT / "generated/drawings/service-robot-concept.svg"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding="utf-8", newline="\n")


def analyse() -> dict[str, object]:
    with (ROOT / "service-robot-mass-ledger.csv").open(newline="", encoding="utf-8") as handle:
        mass_rows = list(csv.DictReader(handle))
    with (REPO / "hardware/release/service-robot-cost-target.csv").open(newline="", encoding="utf-8") as handle:
        cost_rows = list(csv.DictReader(handle))
    with (ROOT / "service-robot-cable-routing.csv").open(newline="", encoding="utf-8") as handle:
        cable_rows = list(csv.DictReader(handle))

    mass = sum(float(row["mass_kg"]) for row in mass_rows)
    cg = [sum(float(row["mass_kg"]) * float(row[f"{axis}_mm"]) for row in mass_rows) / mass for axis in ("x", "y", "z")]
    stabilizer = SPEC["stability"]["deployed_hidden_stabilizer_polygon_mm"]
    roll_tip = math.degrees(math.atan2(stabilizer[0] / 2 - abs(cg[0]), cg[2]))
    pitch_tip = math.degrees(math.atan2(stabilizer[1] / 2 - abs(cg[1]), cg[2]))
    evt_cost = sum(float(row["evt_target_usd"]) for row in cost_rows)
    production_cost = sum(float(row["production_100_target_usd"]) for row in cost_rows)

    mobility = SPEC["mobility"]
    radius_m = mobility["wheel_diameter_mm"] / 2000
    force_n = mass * (
        mobility["maximum_acceleration_mps2"] + 9.80665 * (0.02 + math.sin(math.radians(mobility["maximum_grade_deg"])))
    )
    required_torque_each = force_n * radius_m
    checks = {
        "mass_target_met": mass <= SPEC["target_mass_kg"],
        "evt_cost_target_met": evt_cost <= SPEC["cost_targets_usd"]["evt_unit_hardware_max"],
        "production_cost_target_met": production_cost <= SPEC["cost_targets_usd"]["production_100_unit_bom_max"],
        "two_seven_axis_arms": SPEC["arm"]["quantity"] == 2 and SPEC["arm"]["joint_count_each"] == 7,
        "drive_torque_screen_met": mobility["minimum_continuous_torque_nm_each"] >= required_torque_each * 2,
        "stabilized_tip_screen_met": min(roll_tip, pitch_tip) >= SPEC["stability"]["minimum_static_tip_screen_deg"],
        "physical_and_supplier_gates_open": bool(SPEC["release_blockers"]) and "VALIDATION_REQUIRED" in SPEC["status"],
        "original_appearance_policy_is_explicit": INDUSTRIAL_DESIGN["copying_policy"].startswith("DO_NOT_COPY"),
        "cost_controlled_cover_count_met": len(INDUSTRIAL_DESIGN["exterior_parts"])
        <= INDUSTRIAL_DESIGN["cost_controls"]["maximum_exterior_part_count"],
        "emergency_stops_and_status_light_are_separated": INDUSTRIAL_DESIGN["human_interfaces"]["emergency_stop_count"]
        >= 2
        and INDUSTRIAL_DESIGN["palette"]["safety_red"]["usage"] == "emergency-stop devices only",
        "sensor_windows_are_serviceable": "individually replaceable"
        in INDUSTRIAL_DESIGN["sensor_integration"]["sensor_windows"],
        "cable_routes_are_complete_and_fail_closed": len(cable_rows) >= 10
        and all(row["status"] != "PASS" for row in cable_rows)
        and min(int(row["service_loop_mm"]) for row in cable_rows)
        >= INDUSTRIAL_DESIGN["serviceability"]["minimum_service_loop_mm"],
    }
    return {
        "configuration_id": SPEC["configuration_id"],
        "status": SPEC["status"],
        "engineering_target_pass": all(checks.values()),
        "checks": checks,
        "mass_kg": round(mass, 1),
        "center_of_gravity_mm": [round(value, 1) for value in cg],
        "stabilized_tip_angles_deg": {"roll": round(roll_tip, 1), "pitch": round(pitch_tip, 1)},
        "required_drive_torque_nm_each_before_margin": round(required_torque_each, 1),
        "cost_targets_usd": {"evt": round(evt_cost), "production_100": round(production_cost)},
        "costs_are_quotes": False,
        "mass_is_measured": False,
        "industrial_design_status": INDUSTRIAL_DESIGN["status"],
        "exterior_part_count": len(INDUSTRIAL_DESIGN["exterior_parts"]),
        "cable_route_count": len(cable_rows),
        "release_blockers": SPEC["release_blockers"],
    }


def main() -> int:
    report = analyse()
    write_concept_svg()
    output = ROOT / "generated/service_robot_analysis.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))
    return 0 if report["engineering_target_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
