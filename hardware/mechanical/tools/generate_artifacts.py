# ruff: noqa: E501

from __future__ import annotations

import csv
import json
import math
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "design-spec.json").read_text(encoding="utf-8"))
OUT = ROOT / "generated"


def analyse() -> dict[str, object]:
    components = SPEC["components"]
    arm_mass = max(item["mass_kg"] for item in components if item["name"].endswith("seven_axis_arm"))
    total = sum(item["mass_kg"] for item in components)
    cg = [sum(item["mass_kg"] * item["xyz"][axis] for item in components) / total for axis in range(3)]
    drive_half_support = SPEC["chassis"]["track"] / 2
    stabilized_half_support = SPEC["chassis"]["stabilized_support_width"] / 2
    drive_tip_angle = math.degrees(math.atan2(drive_half_support, cg[2]))
    stabilized_tip_angle = math.degrees(math.atan2(stabilized_half_support, cg[2]))
    drop_energy = total * 9.80665 * SPEC["impact"]["drop_height_m"]
    stop_distance = drop_energy / (total * SPEC["impact"]["design_deceleration_g"] * 9.80665) * 1000
    tray = SPEC["electronics_tray"]
    pcb_width, pcb_depth, _ = tray["pcb_envelope"]
    service_margin = [(tray["width"] - pcb_width) / 2, (tray["depth"] - pcb_depth) / 2]
    return {
        "status": SPEC["validation_status"],
        "mass_kg": round(total, 3),
        "center_of_gravity_mm": [round(value, 1) for value in cg],
        "static_tip_angle_deg": round(stabilized_tip_angle, 1),
        "drive_footprint_tip_angle_deg": round(drive_tip_angle, 1),
        "stabilized_tip_angle_deg": round(stabilized_tip_angle, 1),
        "payload_only_moment_nm": round(
            SPEC["manipulator"]["continuous_payload"]["mass_kg"]
            * 9.80665
            * SPEC["manipulator"]["continuous_payload"]["reach_mm"]
            / 1000,
            1,
        ),
        "arm_plus_payload_screen_moment_nm": round(
            (SPEC["manipulator"]["continuous_payload"]["mass_kg"] + arm_mass)
            * 9.80665
            * SPEC["manipulator"]["continuous_payload"]["reach_mm"]
            / 1000,
            1,
        ),
        "bimanual_shared_workspace_screen_moment_nm": round(
            (2 * arm_mass + SPEC["manipulator"]["bimanual_payload"]["mass_kg"])
            * 9.80665
            * SPEC["manipulator"]["bimanual_payload"]["reach_mm"]
            / 1000,
            1,
        ),
        "drop_energy_j": round(drop_energy, 1),
        "minimum_energy_absorber_stroke_mm": round(stop_distance, 1),
        "vent_area_ratio_outlet_to_inlet": round(
            SPEC["ventilation"]["outlet_area_mm2"] / SPEC["ventilation"]["inlet_area_mm2"], 2
        ),
        "checks": {
            "drive_tip_angle_at_least_25_deg": drive_tip_angle >= 25,
            "stabilized_tip_angle_at_least_35_deg": stabilized_tip_angle >= 35,
            "outlet_area_at_least_inlet": SPEC["ventilation"]["outlet_area_mm2"]
            >= SPEC["ventilation"]["inlet_area_mm2"],
            "absorber_at_least_derived_stroke": SPEC["impact"]["effective_absorber_stroke_mm"] >= stop_distance,
            "pcb_fits_electronics_tray": pcb_width <= tray["width"] and pcb_depth <= tray["depth"],
            "pcb_edge_service_margin_met": min(service_margin) >= tray["minimum_edge_service_margin"],
        },
        "pcb_tray_margin_mm": [tray["width"] - pcb_width, tray["depth"] - pcb_depth],
        "pcb_edge_service_margin_mm": service_margin,
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
    display_width, display_height = SPEC["head"]["display_cutout"]
    display = (
        cq.Workplane("XY")
        .box(display_width, wall * 4, display_height)
        .translate((0, -depth / 2, height - SPEC["head"]["height"] / 2))
    )
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

    chassis_spec = SPEC["chassis"]
    head_spec = SPEC["head"]
    torso_spec = SPEC["torso"]

    chassis = (
        cq.Workplane("XY")
        .box(chassis_spec["width"], chassis_spec["depth"], 112)
        .edges("|Z")
        .fillet(45)
        .translate((0, 0, 84))
    )
    lift_lower = cq.Workplane("XY").box(210, 175, 255).edges("|Z").fillet(22).translate((0, 12, 270))
    lift_upper = cq.Workplane("XY").box(170, 138, 250).edges("|Z").fillet(18).translate((0, 12, 440))
    lifting_platform = lift_lower.union(lift_upper)
    torso = (
        cq.Workplane("XY")
        .box(torso_spec["width"], torso_spec["depth"], torso_spec["height"])
        .edges("|Z")
        .fillet(38)
        .translate((0, 0, 610))
    )
    head = (
        cq.Workplane("XY")
        .box(head_spec["width"], head_spec["depth"], head_spec["height"])
        .edges("|Z")
        .fillet(30)
        .rotate((0, 0, 0), (1, 0, 0), head_spec["tilt_deg"])
        .translate((0, -12, 900))
    )
    face_lens = cq.Workplane("XZ").circle(head_spec["display_cutout"][0] / 2).extrude(5).translate((0, -67, 900))
    tray_spec = SPEC["electronics_tray"]
    tray = (
        cq.Workplane("XY")
        .box(tray_spec["width"], tray_spec["depth"], 4)
        .faces(">Z")
        .workplane()
        .rect(*tray_spec["pcb_mount_pattern"], forConstruction=True)
        .vertices()
        .hole(3.4)
        .translate((0, 0, 120))
    )
    stabilizer = cq.Workplane("XY").box(48, 48, 18).edges("|Z").fillet(10)
    stabilizers = None
    for x in (-286, 286):
        for y in (-281, 281):
            foot = stabilizer.translate((x, y, 38))
            stabilizers = foot if stabilizers is None else stabilizers.union(foot)
    tool_dock = cq.Workplane("XY").box(62, 160, 230).edges("|Z").fillet(18).translate((-178, 86, 357))

    right_arm_points = [
        (176, 118, 770),
        (204, 88, 758),
        (250, 48, 730),
        (375, -105, 625),
        (330, -245, 560),
        (270, -295, 540),
        (225, -318, 528),
        (182, -335, 520),
    ]
    joint_radii = [41, 38, 34, 29, 24, 20, 17]
    left_arm_points = [(-x, y, z) for x, y, z in right_arm_points]

    def make_arm(points: list[tuple[float, float, float]]) -> object:
        arm_solids = []
        for index, (start, end) in enumerate(pairwise(points)):
            start_vector = cq.Vector(*start)
            end_vector = cq.Vector(*end)
            direction = end_vector - start_vector
            radius = max(joint_radii[index] * 0.52, 10)
            arm_solids.append(cq.Solid.makeCylinder(radius, direction.Length, start_vector, direction.normalized()))
            arm_solids.append(cq.Solid.makeSphere(joint_radii[index], start_vector))
        arm_solids.append(cq.Solid.makeSphere(14, cq.Vector(*points[-1])))
        return cq.Compound.makeCompound(arm_solids)

    left_seven_axis_arm = make_arm(left_arm_points)
    right_seven_axis_arm = make_arm(right_arm_points)

    parts = {
        "mobile_base": chassis,
        "lifting_platform": lifting_platform,
        "utility_torso": torso,
        "left_seven_axis_arm": left_seven_axis_arm,
        "right_seven_axis_arm": right_seven_axis_arm,
        "head_module": head.union(face_lens),
        "electronics_tray": tray,
        "stabilizers": stabilizers,
        "tool_dock": tool_dock,
    }
    part_dir = OUT / "parts"
    part_dir.mkdir(exist_ok=True)
    for stale in part_dir.glob("*.step"):
        stale.unlink()
    for name, shape in parts.items():
        part_path = part_dir / f"{name}.step"
        cq.exporters.export(shape, str(part_path), exportType="STEP")
        normalize_step(part_path)
    cq.exporters.export(torso, str(OUT / "enclosure.step"), exportType="STEP")
    normalize_step(OUT / "enclosure.step")

    assembly = cq.Assembly(name="workbench_home_robot")
    assembly.add(chassis, name="mobile_base", color=cq.Color(0.08, 0.10, 0.10))
    assembly.add(lifting_platform, name="lifting_platform", color=cq.Color(0.26, 0.28, 0.27))
    assembly.add(torso, name="utility_torso", color=cq.Color(0.90, 0.89, 0.85))
    assembly.add(head, name="head_module", color=cq.Color(0.90, 0.89, 0.85))
    assembly.add(face_lens, name="face_lens", color=cq.Color(0.03, 0.04, 0.04))
    assembly.add(left_seven_axis_arm, name="left_seven_axis_arm", color=cq.Color(0.26, 0.28, 0.27))
    assembly.add(right_seven_axis_arm, name="right_seven_axis_arm", color=cq.Color(0.26, 0.28, 0.27))
    assembly.add(tray, name="electronics_tray", color=cq.Color(0.42, 0.44, 0.42))
    assembly.add(stabilizers, name="stabilizers", color=cq.Color(0.08, 0.09, 0.09))
    assembly.add(tool_dock, name="tool_dock", color=cq.Color(0.22, 0.24, 0.23))
    assembly_path = OUT / "desk_robot_assembly.step"
    assembly.save(str(assembly_path), exportType="STEP")
    normalize_step(assembly_path)

    exploded = cq.Assembly(name="workbench_home_robot_exploded")
    exploded.add(chassis.translate((0, 0, -100)), name="mobile_base")
    exploded.add(stabilizers.translate((0, 0, -150)), name="stabilizers")
    exploded.add(tray.translate((0, 0, 80)), name="electronics_tray")
    exploded.add(lifting_platform.translate((0, 0, 80)), name="lifting_platform")
    exploded.add(torso.translate((0, 0, 180)), name="utility_torso")
    exploded.add(head.translate((0, 0, 300)), name="head_module")
    exploded.add(left_seven_axis_arm.translate((-180, 0, 120)), name="left_seven_axis_arm")
    exploded.add(right_seven_axis_arm.translate((180, 0, 120)), name="right_seven_axis_arm")
    exploded.add(tool_dock.translate((-120, 0, 120)), name="tool_dock")
    exploded_path = OUT / "desk_robot_exploded.step"
    exploded.save(str(exploded_path), exportType="STEP")
    normalize_step(exploded_path)
    return True


def write_engineering_drawings(report: dict[str, object]) -> None:
    drawings = OUT / "drawings"
    drawings.mkdir(exist_ok=True)
    width = SPEC["enclosure"]["width"]
    height = SPEC["enclosure"]["height"]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="760" viewBox="0 0 1200 760">
<style>text{{font-family:Arial,sans-serif;fill:#17201f}} .shell{{fill:#ecece7;stroke:#17201f;stroke-width:3}} .frame{{fill:#404745;stroke:#17201f;stroke-width:3}} .joint{{fill:#202625;stroke:#7a807d;stroke-width:5}} .dim{{stroke:#287b70;stroke-width:2;marker-start:url(#a);marker-end:url(#a)}} .note{{font-size:17px}}</style>
<defs><marker id="a" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M8,0 L0,4 L8,8" fill="none" stroke="#287b70"/></marker></defs>
<text x="36" y="44" font-size="28" font-weight="bold">Workbench Home Robot - General Arrangement - REV D</text>
<text x="36" y="72" class="note">Dual seven-axis arms + 350 mm braked lift; concept geometry; mm</text>
<rect class="frame" x="115" y="590" width="270" height="72" rx="24"/><rect class="frame" x="188" y="452" width="124" height="150" rx="16"/>
<path class="shell" d="M160 218 Q160 190 190 188 L315 188 Q342 190 342 220 L328 456 L174 456 Z"/>
<rect class="frame" x="230" y="167" width="44" height="34" rx="12"/><rect class="shell" x="185" y="100" width="135" height="70" rx="28"/><circle cx="252" cy="135" r="25" fill="#101716"/><circle cx="243" cy="132" r="4" fill="#72c9b4"/><circle cx="261" cy="132" r="4" fill="#72c9b4"/>
<polyline points="342,318 382,306 420,350 458,405 493,444 525,466 553,480" fill="none" stroke="#404745" stroke-width="22" stroke-linecap="round" stroke-linejoin="round"/>
<g>{''.join(f'<circle class="joint" cx="{x}" cy="{y}" r="{r}"/>' for x, y, r in [(342,318,22),(382,306,20),(420,350,18),(458,405,16),(493,444,14),(525,466,12),(553,480,10)])}</g>
<polyline points="163,318 126,306 94,350 72,405 58,444 48,466 40,480" fill="none" stroke="#404745" stroke-width="22" stroke-linecap="round" stroke-linejoin="round"/>
<g>{''.join(f'<circle class="joint" cx="{x}" cy="{y}" r="{r}"/>' for x, y, r in [(163,318,22),(126,306,20),(94,350,18),(72,405,16),(58,444,14),(48,466,12),(40,480,10)])}</g>
<text x="195" y="224" class="note">independent neck</text><text x="183" y="294" class="note">torso-side shoulders</text>
<line class="dim" x1="90" y1="112" x2="90" y2="662"/><text x="50" y="410" class="note" transform="rotate(-90 50 410)">max {height}</text>
<line class="dim" x1="115" y1="700" x2="385" y2="700"/><text x="222" y="725" class="note">base {width}</text>
<text x="630" y="130" font-size="21" font-weight="bold">LIFT STATES</text>
<rect class="frame" x="650" y="520" width="190" height="70" rx="22"/><rect class="frame" x="710" y="385" width="70" height="145" rx="14"/><rect class="shell" x="680" y="245" width="130" height="145" rx="30"/>
<rect class="frame" x="930" y="520" width="190" height="70" rx="22"/><rect class="frame" x="990" y="260" width="70" height="270" rx="14"/><rect class="shell" x="960" y="120" width="130" height="145" rx="30"/>
<line class="dim" x1="875" y1="260" x2="875" y2="385"/><text x="892" y="330" class="note">travel {SPEC["lifting_platform"]["travel"]}</text>
<text x="675" y="625" class="note">LOW / DRIVE</text><text x="958" y="625" class="note">RAISED / WORK</text>
<text x="630" y="680" class="note">CG Z={report["center_of_gravity_mm"][2]} · drive tip={report["drive_footprint_tip_angle_deg"]} deg · stabilized tip={report["stabilized_tip_angle_deg"]} deg</text>
<text x="630" y="712" class="note">Manipulation requires wheel brakes + deployed support feet.</text>
</svg>"""
    (drawings / "general-arrangement.svg").write_text(svg, encoding="utf-8", newline="\n")
    thermal = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="420" viewBox="0 0 1100 420">
<style>text{{font-family:Arial,sans-serif}}.box{{fill:#eef3f6;stroke:#222;stroke-width:2}}.flow{{stroke:#00897b;stroke-width:12;fill:none;marker-end:url(#arrow)}}</style>
<defs><marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto"><path d="M0,0 L12,6 L0,12 z" fill="#00897b"/></marker></defs>
<text x="30" y="45" font-size="28" font-weight="bold">Thermal Airflow and Conduction Path</text>
<rect class="box" x="60" y="145" width="180" height="120"/><text x="86" y="210" font-size="22">{SPEC["ventilation"]["inlet_area_mm2"]} mm2 inlet</text>
<rect class="box" x="430" y="120" width="220" height="170"/><text x="485" y="190" font-size="22">Jetson 40 W</text><text x="470" y="225" font-size="18">pad -> chassis</text>
<rect class="box" x="820" y="145" width="200" height="120"/><text x="840" y="210" font-size="22">{SPEC["ventilation"]["outlet_area_mm2"]} mm2 outlet</text>
<path class="flow" d="M240 205 C330 205 345 185 430 185"/><path class="flow" d="M650 185 C735 185 745 205 820 205"/>
<text x="310" y="350" font-size="20">{SPEC["ventilation"]["fan_mm"]} mm fan; electronics airflow isolated from food-contact tool zone</text>
</svg>"""
    (drawings / "thermal-flow.svg").write_text(thermal, encoding="utf-8", newline="\n")
    fea = {
        "method": "energy and equivalent-static screening; nonlinear FEA and physical drop remain required",
        "drop_force_n_at_design_g": round(report["mass_kg"] * SPEC["impact"]["design_deceleration_g"] * 9.80665, 1),
        "drop_energy_j": report["drop_energy_j"],
        "effective_stroke_mm": SPEC["impact"]["effective_absorber_stroke_mm"],
        "estimated_bumper_contact_area_mm2": 18000,
        "estimated_average_compressive_stress_mpa": round(report["mass_kg"] * SPEC["impact"]["design_deceleration_g"] * 9.80665 / 18000, 3),
        "acceptance": {"peak_deceleration_g": SPEC["impact"]["design_deceleration_g"], "no_battery_contact": True, "no_sharp_shell_fracture": True},
    }
    (OUT / "drop-screening.json").write_text(json.dumps(fea, indent=2) + "\n", encoding="utf-8")
    sequence = [
        {"step": 10, "part": "mobile_base", "fastener": "fixture datum A + brake check"},
        {"step": 20, "part": "stabilizers", "fastener": "4x captive M6 + deployed-foot witness"},
        {"step": 30, "part": "lifting_platform", "fastener": "dual screw synchronization + lock pins"},
        {"step": 40, "part": "electronics_tray", "fastener": "4x M3x8 @ 0.55 Nm"},
        {"step": 50, "part": "utility_torso", "fastener": "8x M4 captive @ 1.2 Nm"},
        {"step": 60, "part": "left_seven_axis_arm", "fastener": "left shoulder datum + torque witness"},
        {"step": 70, "part": "right_seven_axis_arm", "fastener": "right shoulder datum + torque witness"},
        {"step": 80, "part": "head_module", "fastener": "4x M4 captive @ 0.8 Nm"},
        {"step": 90, "part": "tool_dock", "fastener": "3x M4 captive @ 0.8 Nm"},
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
        ["ME-C01", "Mobile base and enclosed drive skirt", "5052-H32 aluminium + TPU", 1],
        ["ME-C02", "Dual-screw lifting platform", "6061-T6 aluminium + steel screws", 1],
        ["ME-C03", "Utility torso and parcel bay", "mineral PC-ABS + recycled PET", 1],
        ["ME-D04", "Seven-axis arm joint set", "bead-blasted anodized aluminium", 2],
        ["ME-C05", "Smoked glass head module", "chemically strengthened glass + PC-ABS", 1],
        ["ME-C06", "Deployable stabilizer feet", "steel core + charcoal TPU", 4],
        ["ME-C07", "Tool dock and quick-change datum", "6061-T6 aluminium + PEEK", 1],
        ["ISO4762-M4", "Captive socket screw", "A2-70 stainless", 28],
        ["LIFT-LOCK-01", "Normally-closed brake and lock pin set", "steel + spring", 2],
    ]
    with (OUT / "bom.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["part_number", "description", "material", "quantity"])
        writer.writerows(rows)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
