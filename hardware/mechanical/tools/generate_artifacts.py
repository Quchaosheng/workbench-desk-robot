# ruff: noqa: E501

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "design-spec.json").read_text(encoding="utf-8"))
OUT = ROOT / "generated"


def analyse() -> dict[str, object]:
    components = SPEC["components"]
    total = sum(item["mass_kg"] for item in components)
    cg = [sum(item["mass_kg"] * item["xyz"][axis] for item in components) / total for axis in range(3)]
    half_support = SPEC["chassis"]["track"] / 2
    tip_angle = math.degrees(math.atan2(half_support, cg[2]))
    drop_energy = total * 9.80665 * SPEC["impact"]["drop_height_m"]
    stop_distance = drop_energy / (total * SPEC["impact"]["design_deceleration_g"] * 9.80665) * 1000
    tray = SPEC["electronics_tray"]
    pcb_width, pcb_depth, _ = tray["pcb_envelope"]
    return {
        "status": "ANALYTICAL_ONLY_PHYSICAL_VALIDATION_REQUIRED",
        "mass_kg": round(total, 3),
        "center_of_gravity_mm": [round(value, 1) for value in cg],
        "static_tip_angle_deg": round(tip_angle, 1),
        "drop_energy_j": round(drop_energy, 1),
        "minimum_energy_absorber_stroke_mm": round(stop_distance, 1),
        "vent_area_ratio_outlet_to_inlet": round(
            SPEC["ventilation"]["outlet_area_mm2"] / SPEC["ventilation"]["inlet_area_mm2"], 2
        ),
        "checks": {
            "tip_angle_at_least_35_deg": tip_angle >= 35,
            "outlet_area_at_least_inlet": SPEC["ventilation"]["outlet_area_mm2"]
            >= SPEC["ventilation"]["inlet_area_mm2"],
            "absorber_at_least_derived_stroke": SPEC["impact"]["effective_absorber_stroke_mm"] >= stop_distance,
            "pcb_fits_electronics_tray": pcb_width <= tray["width"] and pcb_depth <= tray["depth"],
        },
        "pcb_tray_margin_mm": [tray["width"] - pcb_width, tray["depth"] - pcb_depth],
    }


def step_box(width: float, depth: float, height: float) -> str:
    # AP203 faceted envelope with six closed faces; origin is centred on X/Y.
    pts = [
        (-width / 2, -depth / 2, 0),
        (width / 2, -depth / 2, 0),
        (width / 2, depth / 2, 0),
        (-width / 2, depth / 2, 0),
        (-width / 2, -depth / 2, height),
        (width / 2, -depth / 2, height),
        (width / 2, depth / 2, height),
        (-width / 2, depth / 2, height),
    ]
    lines = [
        "ISO-10303-21;",
        "HEADER;",
        "FILE_DESCRIPTION(('DESK ROBOT ENVELOPE'),'2;1');",
        "FILE_NAME('enclosure.step','2026-08-06T00:00:00',('Workbench-1'),('Quchaosheng'),'Codex','Workbench-1','');",
        "FILE_SCHEMA(('CONFIG_CONTROL_DESIGN'));",
        "ENDSEC;",
        "DATA;",
        "#1=APPLICATION_CONTEXT('configuration controlled 3d designs of mechanical parts and assemblies');",
        "#2=PRODUCT_CONTEXT('',#1,'mechanical');",
        "#3=PRODUCT('DESK_ROBOT_ENVELOPE','DESK_ROBOT_ENVELOPE','',(#2));",
    ]
    for index, point in enumerate(pts, start=10):
        lines.append(f"#{index}=CARTESIAN_POINT('',({point[0]:.3f},{point[1]:.3f},{point[2]:.3f}));")
    lines += [
        "#30=POLYLINE('',(#10,#11,#12,#13,#10));",
        "#31=POLYLINE('',(#14,#15,#16,#17,#14));",
        "#32=POLYLINE('',(#10,#11,#15,#14,#10));",
        "#33=POLYLINE('',(#11,#12,#16,#15,#11));",
        "#34=POLYLINE('',(#12,#13,#17,#16,#12));",
        "#35=POLYLINE('',(#13,#10,#14,#17,#13));",
        "ENDSEC;",
        "END-ISO-10303-21;",
    ]
    return "\n".join(lines) + "\n"


def export_solid_step(path: Path) -> bool:
    try:
        import cadquery as cq
    except ImportError:
        return False

    enclosure = SPEC["enclosure"]
    width, depth, height = enclosure["width"], enclosure["depth"], enclosure["height"]
    wall, radius = enclosure["wall"], enclosure["corner_radius"]
    outer = cq.Workplane("XY").box(width, depth, height).edges("|Z").fillet(radius).translate((0, 0, height / 2))
    inner_height = height - wall
    inner = (
        cq.Workplane("XY")
        .box(width - 2 * wall, depth - 2 * wall, inner_height)
        .edges("|Z")
        .fillet(radius - wall)
        .translate((0, 0, wall + inner_height / 2))
    )
    shell = outer.cut(inner)
    display = cq.Workplane("XY").box(150, wall * 4, 72).translate((0, -depth / 2, 261))
    shell = shell.cut(display)
    cq.exporters.export(shell, str(path), exportType="STEP")
    normalized = "\n".join(line.rstrip() for line in path.read_text(encoding="ascii").splitlines()) + "\n"
    path.write_text(normalized, encoding="ascii", newline="\n")
    return True


def normalize_step(path: Path) -> None:
    normalized = "\n".join(line.rstrip() for line in path.read_text(encoding="ascii").splitlines()) + "\n"
    path.write_text(normalized, encoding="ascii", newline="\n")


def export_cad_package() -> bool:
    try:
        import cadquery as cq
    except ImportError:
        return False

    enclosure = SPEC["enclosure"]
    width, depth, height = enclosure["width"], enclosure["depth"], enclosure["height"]
    wall, radius = enclosure["wall"], enclosure["corner_radius"]
    outer = cq.Workplane("XY").box(width, depth, height).edges("|Z").fillet(radius).translate((0, 0, height / 2))
    inner_height = height - wall
    inner = (
        cq.Workplane("XY")
        .box(width - 2 * wall, depth - 2 * wall, inner_height)
        .edges("|Z")
        .fillet(radius - wall)
        .translate((0, 0, wall + inner_height / 2))
    )
    shell = outer.cut(inner).cut(cq.Workplane("XY").box(150, wall * 4, 72).translate((0, -depth / 2, 261)))
    chassis = (
        cq.Workplane("XY")
        .box(260, 220, 4)
        .faces(">Z")
        .workplane()
        .rect(230, 190, forConstruction=True)
        .vertices()
        .hole(4.2)
        .translate((0, 0, 24))
    )
    tray = (
        cq.Workplane("XY")
        .box(220, 170, 3)
        .faces(">Z")
        .workplane()
        .rect(*SPEC["electronics_tray"]["pcb_mount_pattern"], forConstruction=True)
        .vertices()
        .hole(3.4)
        .translate((0, 0, 43))
    )
    display_bracket = (
        cq.Workplane("XZ")
        .rect(180, 92)
        .extrude(4)
        .cut(cq.Workplane("XZ").rect(150, 72).extrude(6))
        .translate((0, -116, 261))
    )
    bumper_outer = cq.Workplane("XY").box(width + 16, depth + 16, 24).edges("|Z").fillet(radius + 8)
    bumper_inner = cq.Workplane("XY").box(width, depth, 26).edges("|Z").fillet(radius)
    bumper = bumper_outer.cut(bumper_inner).translate((0, 0, 22))
    motor_bracket = cq.Workplane("XY").box(45, 35, 4).union(cq.Workplane("XZ").box(45, 28, 4).translate((0, -15.5, 14)))

    parts = {
        "upper_shell": shell,
        "lower_chassis": chassis,
        "electronics_tray": tray,
        "display_bracket": display_bracket,
        "impact_bumper": bumper,
        "motor_bracket": motor_bracket,
    }
    part_dir = OUT / "parts"
    part_dir.mkdir(exist_ok=True)
    for name, shape in parts.items():
        part_path = part_dir / f"{name}.step"
        cq.exporters.export(shape, str(part_path), exportType="STEP")
        normalize_step(part_path)
    cq.exporters.export(shell, str(OUT / "enclosure.step"), exportType="STEP")
    normalize_step(OUT / "enclosure.step")

    assembly = cq.Assembly(name="desk_robot")
    assembly.add(shell, name="upper_shell", color=cq.Color(0.75, 0.75, 0.78, 0.45))
    assembly.add(chassis, name="lower_chassis", color=cq.Color(0.25, 0.25, 0.28))
    assembly.add(tray, name="electronics_tray", color=cq.Color(0.45, 0.48, 0.52))
    assembly.add(display_bracket, name="display_bracket", color=cq.Color(0.1, 0.1, 0.12))
    assembly.add(bumper, name="impact_bumper", color=cq.Color(0.95, 0.35, 0.05))
    assembly.add(motor_bracket.translate((-85, 0, 38)), name="motor_bracket_left")
    assembly.add(motor_bracket.translate((85, 0, 38)), name="motor_bracket_right")
    assembly_path = OUT / "desk_robot_assembly.step"
    assembly.save(str(assembly_path), exportType="STEP")
    normalize_step(assembly_path)

    exploded = cq.Assembly(name="desk_robot_exploded")
    exploded.add(chassis.translate((0, 0, -30)), name="lower_chassis")
    exploded.add(tray.translate((0, 0, 45)), name="electronics_tray")
    exploded.add(shell.translate((0, 0, 130)), name="upper_shell")
    exploded.add(display_bracket.translate((0, -35, 180)), name="display_bracket")
    exploded.add(bumper.translate((0, 0, -70)), name="impact_bumper")
    exploded_path = OUT / "desk_robot_exploded.step"
    exploded.save(str(exploded_path), exportType="STEP")
    normalize_step(exploded_path)
    return True


def write_engineering_drawings(report: dict[str, object]) -> None:
    drawings = OUT / "drawings"
    drawings.mkdir(exist_ok=True)
    width = SPEC["enclosure"]["width"]
    depth = SPEC["enclosure"]["depth"]
    height = SPEC["enclosure"]["height"]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="760" viewBox="0 0 1200 760">
<style>text{{font-family:Arial,sans-serif;fill:#111}} .part{{fill:#e8edf2;stroke:#111;stroke-width:2}} .dim{{stroke:#1769aa;stroke-width:2;marker-start:url(#a);marker-end:url(#a)}} .note{{font-size:18px}}</style>
<defs><marker id="a" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M8,0 L0,4 L8,8" fill="none" stroke="#1769aa"/></marker></defs>
<text x="40" y="45" font-size="28" font-weight="bold">Workbench-1 General Arrangement - mm - REV A</text>
<rect class="part" x="90" y="120" width="{width * 1.5}" height="{height * 1.5}" rx="27"/>
<rect x="187" y="450" width="225" height="108" fill="#20252b" stroke="#111" stroke-width="2"/>
<line class="dim" x1="90" y1="90" x2="510" y2="90"/><text x="280" y="80" class="note">{width}</text>
<line class="dim" x1="55" y1="120" x2="55" y2="615"/><text x="12" y="375" class="note" transform="rotate(-90 12 375)">{height}</text>
<text x="120" y="650" class="note">Front: display cutout 150 x 72; nominal wall 2.5</text>
<rect class="part" x="660" y="170" width="{width * 1.5}" height="{depth * 1.5}" rx="27"/>
<line class="dim" x1="660" y1="140" x2="1080" y2="140"/><text x="850" y="130" class="note">{width}</text>
<line class="dim" x1="1120" y1="170" x2="1120" y2="530"/><text x="1140" y="370" class="note" transform="rotate(-90 1140 370)">{depth}</text>
<rect x="675" y="185" width="390" height="330" fill="none" stroke="#e65c00" stroke-width="12" rx="24"/>
<text x="700" y="565" class="note">8 TPU skin over 24 effective compliant stroke</text>
<text x="660" y="625" class="note">CG Z={report['center_of_gravity_mm'][2]}; static tip angle={report['static_tip_angle_deg']} deg</text>
<text x="660" y="660" class="note">ISO 2768-m unless noted; prototype only until physical validation</text>
</svg>"""
    (drawings / "general-arrangement.svg").write_text(svg, encoding="utf-8", newline="\n")
    thermal = """<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="420" viewBox="0 0 1100 420">
<style>text{font-family:Arial,sans-serif}.box{fill:#eef3f6;stroke:#222;stroke-width:2}.flow{stroke:#00897b;stroke-width:12;fill:none;marker-end:url(#arrow)}</style>
<defs><marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto"><path d="M0,0 L12,6 L0,12 z" fill="#00897b"/></marker></defs>
<text x="30" y="45" font-size="28" font-weight="bold">Thermal Airflow and Conduction Path</text>
<rect class="box" x="60" y="145" width="180" height="120"/><text x="95" y="210" font-size="22">1800 mm2 inlet</text>
<rect class="box" x="430" y="120" width="220" height="170"/><text x="485" y="190" font-size="22">Jetson 40 W</text><text x="470" y="225" font-size="18">pad -> chassis</text>
<rect class="box" x="820" y="145" width="200" height="120"/><text x="850" y="210" font-size="22">2200 mm2 outlet</text>
<path class="flow" d="M240 205 C330 205 345 185 430 185"/><path class="flow" d="M650 185 C735 185 745 205 820 205"/>
<text x="360" y="350" font-size="20">60 mm fan; lower-front to upper-rear; outlet/inlet area ratio 1.22</text>
</svg>"""
    (drawings / "thermal-flow.svg").write_text(thermal, encoding="utf-8", newline="\n")
    fea = {
        "method": "energy and equivalent-static screening; nonlinear FEA and physical drop remain required",
        "drop_force_n_at_35g": round(report["mass_kg"] * 35 * 9.80665, 1),
        "drop_energy_j": report["drop_energy_j"],
        "effective_stroke_mm": SPEC["impact"]["effective_absorber_stroke_mm"],
        "estimated_bumper_contact_area_mm2": 18000,
        "estimated_average_compressive_stress_mpa": round(report["mass_kg"] * 35 * 9.80665 / 18000, 3),
        "acceptance": {"peak_deceleration_g": 35, "no_battery_contact": True, "no_sharp_shell_fracture": True},
    }
    (OUT / "drop-screening.json").write_text(json.dumps(fea, indent=2) + "\n", encoding="utf-8")
    sequence = [
        {"step": 10, "part": "lower_chassis", "fastener": "fixture datum A"},
        {"step": 20, "part": "motor_brackets", "fastener": "8x M3x8 @ 0.55 Nm"},
        {"step": 30, "part": "electronics_tray", "fastener": "4x M3x8 @ 0.55 Nm"},
        {"step": 40, "part": "display_bracket", "fastener": "4x M3x6 @ 0.25 Nm"},
        {"step": 50, "part": "upper_shell", "fastener": "8x M3x8 @ 0.25 Nm"},
        {"step": 60, "part": "impact_bumper", "fastener": "snap + 4 retained screws"},
    ]
    (OUT / "assembly-sequence.json").write_text(json.dumps(sequence, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    enclosure = SPEC["enclosure"]
    report = analyse()
    if not all(report["checks"].values()):
        raise SystemExit(f"mechanical design check failed: {report['checks']}")
    (OUT / "analysis.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    step_path = OUT / "enclosure.step"
    cad_exported = export_cad_package()
    if not cad_exported and not export_solid_step(step_path) and not step_path.exists():
        step_path.write_text(step_box(enclosure["width"], enclosure["depth"], enclosure["height"]), encoding="ascii")
    write_engineering_drawings(report)
    rows = [
        ["ME-001", "Lower chassis", "5052-H32 aluminium", 1],
        ["ME-002", "Upper shell", "PC-ABS FR", 1],
        ["ME-003", "Impact bumper", "TPU 95A", 1],
        ["ME-004", "Electronics tray", "5052-H32 aluminium", 1],
        ["ISO4762-M3x8", "Socket screw", "A2-70 stainless", 16],
        ["DIN934-M3", "Hex nut", "A2 stainless", 16],
        ["ME-005", "Motor bracket", "6061-T6 aluminium", 2],
        ["ME-006", "Display bracket", "PC-ABS FR", 1],
    ]
    with (OUT / "bom.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["part_number", "description", "material", "quantity"])
        writer.writerows(rows)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
