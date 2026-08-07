# ruff: noqa: E501

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


def write_controlled_outputs() -> None:
    generated = ROOT / "generated"
    generated.mkdir(exist_ok=True)
    with (ROOT / "routing.csv").open(newline="", encoding="utf-8") as handle:
        route = list(csv.DictReader(handle))

    with (generated / "quality-traveller.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = [
            "serial",
            "operation",
            "station",
            "quality_gate",
            "fixture_id",
            "calibration_due",
            "operator",
            "start_time",
            "end_time",
            "result",
            "defect_code",
            "evidence_uri",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in route:
            writer.writerow({"operation": row["op"], "station": row["station"], "quality_gate": row["quality_gate"]})

    with (generated / "pilot-log.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = [
            "serial",
            "build_date",
            "touch_minutes",
            "first_pass",
            "first_failed_gate",
            "defect_code",
            "rework_cycles",
            "final_result",
            "evidence_uri",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for serial in range(1, 21):
            writer.writerow({"serial": f"WB1-EVT-{serial:03d}", "final_result": "NOT_BUILT"})

    cost_rows = [
        ["direct_material", "CNY/unit", "", "purchase orders"],
        ["touch_minutes", "min/unit", "103", "validated route baseline"],
        ["burdened_labor_rate", "CNY/hour", "", "finance approved rate"],
        ["fixture_rate", "CNY/hour", "", "depreciation and calibration"],
        ["first_pass_yield", "fraction", "", "20-unit pilot"],
        ["packaging", "CNY/unit", "", "approved supplier quote"],
        ["freight", "CNY/unit", "", "route-specific quote"],
        ["warranty_reserve", "CNY/unit", "", "quality/finance estimate"],
    ]
    with (generated / "unit-cost-inputs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["input", "unit", "value", "evidence_source"])
        writer.writerows(cost_rows)

    layout = """<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="760" viewBox="0 0 1400 760">
<style>text{font-family:Arial,sans-serif}.s{fill:#e8edf2;stroke:#17202a;stroke-width:3}.q{fill:#ffe0b2;stroke:#e65100;stroke-width:3}.a{stroke:#00897b;stroke-width:8;fill:none;marker-end:url(#m)}</style>
<defs><marker id="m" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#00897b"/></marker></defs>
<text x="40" y="45" font-size="30" font-weight="bold">Workbench-1 U-cell Layout - minimum aisle 1.2 m</text>
<rect class="s" x="70" y="120" width="190" height="110"/><text x="105" y="180" font-size="22">Receive / Kit</text>
<rect class="s" x="350" y="120" width="190" height="110"/><text x="395" y="180" font-size="22">SMT / AOI</text>
<rect class="q" x="630" y="120" width="190" height="110"/><text x="660" y="180" font-size="22">Guarded PCBA Test</text>
<rect class="s" x="910" y="120" width="190" height="110"/><text x="950" y="180" font-size="22">Mechanical Cell</text>
<rect class="q" x="910" y="430" width="190" height="110"/><text x="935" y="490" font-size="22">Safety / Functional</text>
<rect class="s" x="630" y="430" width="190" height="110"/><text x="680" y="490" font-size="22">Final / Pack</text>
<rect fill="#ffcdd2" stroke="#b71c1c" stroke-width="3" x="70" y="430" width="250" height="110"/><text x="120" y="490" font-size="22">MRB / Quarantine</text>
<path class="a" d="M260 175 H350"/><path class="a" d="M540 175 H630"/><path class="a" d="M820 175 H910"/><path class="a" d="M1005 230 V430"/><path class="a" d="M910 485 H820"/>
<text x="410" y="670" font-size="22">Material flows one way; quarantine is fenced off the forward route.</text>
</svg>"""
    (generated / "line-layout.svg").write_text(layout, encoding="utf-8", newline="\n")

    fixture = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="700" viewBox="0 0 1200 700">
<style>text{font-family:Arial,sans-serif}.p{fill:#edf2f5;stroke:#111;stroke-width:3}.d{stroke:#1565c0;stroke-width:2}</style>
<text x="35" y="45" font-size="28" font-weight="bold">FX-01 Chassis Datum Nest / FX-02 Guarded Electrical Jig</text>
<rect class="p" x="80" y="120" width="520" height="440"/><rect x="110" y="150" width="460" height="380" fill="none" stroke="#e65100" stroke-width="4"/>
<circle cx="130" cy="170" r="9"/><circle cx="550" cy="170" r="9"/><circle cx="130" cy="510" r="9"/><circle cx="550" cy="510" r="9"/>
<text x="190" y="600" font-size="20">Nest 260 x 220; datum pins 230 x 190; flatness 0.20</text>
<rect class="p" x="700" y="120" width="400" height="440"/><rect x="750" y="180" width="300" height="220" fill="#fff3e0" stroke="#e65100" stroke-width="4"/>
<text x="785" y="290" font-size="22">DUT guarded volume</text><circle cx="770" cy="480" r="35" fill="#d32f2f"/><text x="825" y="490" font-size="22">Emergency disconnect</text>
<text x="720" y="600" font-size="20">0-60 V / 10 A; Kelvin probes; interlocked lid</text>
</svg>"""
    (generated / "fixture-drawings.svg").write_text(fixture, encoding="utf-8", newline="\n")

    packaging = """<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="650" viewBox="0 0 1000 650">
<style>text{font-family:Arial,sans-serif}.c{fill:#d7ccc8;stroke:#4e342e;stroke-width:4}.f{fill:#bbdefb;stroke:#1565c0;stroke-width:3}</style>
<text x="35" y="45" font-size="28" font-weight="bold">Workbench-1 Transit Pack - REV A</text>
<rect class="c" x="160" y="100" width="680" height="470"/><rect class="f" x="220" y="160" width="560" height="350" rx="35"/>
<rect x="290" y="200" width="420" height="270" rx="25" fill="#eceff1" stroke="#263238" stroke-width="3"/>
<text x="385" y="350" font-size="24">Robot envelope</text><text x="230" y="610" font-size="20">Double-wall carton; >=50 mm EPE/EPP all faces; display guard; wheel restraints</text>
</svg>"""
    (generated / "packaging-drawing.svg").write_text(packaging, encoding="utf-8", newline="\n")


def main() -> None:
    report = validate()
    generated = ROOT / "generated"
    generated.mkdir(exist_ok=True)
    write_controlled_outputs()
    (generated / "route_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["pass"]:
        raise SystemExit("manufacturing route validation failed")


if __name__ == "__main__":
    main()
