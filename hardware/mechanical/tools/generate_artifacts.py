# ruff: noqa: E501

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "design-spec.json").read_text(encoding="utf-8"))
OUT = ROOT / "generated"


def box_limits(dimensions: list[float], position: list[float]) -> list[tuple[float, float]]:
    return [(position[axis] - dimensions[axis] / 2, position[axis] + dimensions[axis] / 2) for axis in range(3)]


def box_clearance(
    first_dimensions: list[float],
    first_position: list[float],
    second_dimensions: list[float],
    second_position: list[float],
) -> float:
    axis_gaps = [
        abs(first_position[axis] - second_position[axis]) - (first_dimensions[axis] + second_dimensions[axis]) / 2
        for axis in range(3)
    ]
    positive_gaps = [gap for gap in axis_gaps if gap >= 0]
    return min(positive_gaps) if positive_gaps else max(axis_gaps)


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
    service_margin = [(tray["width"] - pcb_width) / 2, (tray["depth"] - pcb_depth) / 2]
    traction = SPEC["traction_integration"]
    battery = SPEC["battery_integration"]
    battery_dimensions = battery["reserved_envelope_mm"]
    battery_limits = box_limits(battery_dimensions, battery["xyz"])
    motor_dimensions = traction["reserved_motor_envelope"]
    motors = traction["motor_envelopes"]
    childboard = traction["childboard"]
    wheel_spec = SPEC["chassis"]["wheels"]
    wheel_dimensions = [wheel_spec["diameter_mm"], wheel_spec["width_mm"], wheel_spec["diameter_mm"]]
    wheel_centres = wheel_spec["centres"]
    wheel_limits = [box_limits(wheel_dimensions, wheel["xyz"]) for wheel in wheel_centres]
    childboard_dimensions = childboard["envelope"]
    childboard_limits = box_limits(childboard_dimensions, childboard["xyz"])
    motor_limits = [box_limits(motor_dimensions, motor["xyz"]) for motor in motors]
    chassis_half_width = SPEC["chassis"]["width"] / 2
    chassis_half_depth = SPEC["chassis"]["depth"] / 2
    enclosure_inner_half_width = (SPEC["enclosure"]["width"] - 2 * SPEC["enclosure"]["wall"]) / 2
    enclosure_inner_half_depth = (SPEC["enclosure"]["depth"] - 2 * SPEC["enclosure"]["wall"]) / 2
    enclosure_inner_height = SPEC["enclosure"]["height"] - SPEC["enclosure"]["wall"]
    controller_service_top = tray["mount_plane_z"] + tray["clearance_above"]
    controller_to_childboard_clearance = childboard_limits[2][0] - controller_service_top
    rear_connector_corridor = enclosure_inner_half_depth - childboard_limits[1][1]
    motor_to_childboard_clearances = [
        box_clearance(motor_dimensions, motor["xyz"], childboard_dimensions, childboard["xyz"]) for motor in motors
    ]
    minimum_motor_to_childboard_clearance = min(motor_to_childboard_clearances)
    battery_to_motor_clearances = [
        box_clearance(battery_dimensions, battery["xyz"], motor_dimensions, motor["xyz"]) for motor in motors
    ]
    battery_to_wheel_clearances = [
        box_clearance(battery_dimensions, battery["xyz"], wheel_dimensions, wheel["xyz"]) for wheel in wheel_centres
    ]
    battery_to_tray_clearance = box_clearance(
        battery_dimensions,
        battery["xyz"],
        [tray["width"], tray["depth"], 3],
        [0, 0, tray["mount_plane_z"] - 1.5],
    )
    battery_to_childboard_clearance = box_clearance(
        battery_dimensions, battery["xyz"], childboard_dimensions, childboard["xyz"]
    )
    childboard_mount_edge_margins = [
        (childboard_dimensions[axis] - childboard["mount_pattern"][axis]) / 2 for axis in range(2)
    ]
    support = childboard["mount_support"]
    support_top_z = support["plate_center_z_mm"] + support["plate_thickness_mm"] / 2
    childboard_bottom_z = childboard_limits[2][0]
    wheel_x_values = sorted({wheel["xyz"][0] for wheel in wheel_centres})
    wheel_y_values = sorted({wheel["xyz"][1] for wheel in wheel_centres})
    wheelbase = wheel_x_values[-1] - wheel_x_values[0] if len(wheel_x_values) == 2 else 0
    track = wheel_y_values[-1] - wheel_y_values[0] if len(wheel_y_values) == 2 else 0
    wheel_overhang_allowance = (wheel_dimensions[1] / 2) - (SPEC["chassis"]["depth"] - SPEC["chassis"]["track"]) / 2
    motor_positions_symmetric = (
        len(motors) == 2
        and {motor["side"] for motor in motors} == {"left", "right"}
        and motors[0]["xyz"][0] == -motors[1]["xyz"][0]
        and motors[0]["xyz"][1:] == motors[1]["xyz"][1:]
    )
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
            "pcb_edge_service_margin_met": min(service_margin) >= tray["minimum_edge_service_margin"],
            "four_wheel_envelopes_declared": wheel_spec["count"] == 4 and len(wheel_centres) == 4,
            "wheelbase_and_track_match_chassis_datums": (
                wheelbase == SPEC["chassis"]["wheelbase"] and track == SPEC["chassis"]["track"]
            ),
            "wheel_envelopes_fit_chassis_projection": all(
                abs(limit[0][0]) <= chassis_half_width
                and abs(limit[1][0]) <= chassis_half_depth + wheel_overhang_allowance
                for limit in wheel_limits
            ),
            "wheel_bottom_matches_ground_clearance": all(
                abs(limit[2][0] - SPEC["chassis"]["ground_clearance"]) <= 0.01 for limit in wheel_limits
            ),
            "battery_envelope_is_declared": len(battery_dimensions) == 3 and len(battery["xyz"]) == 3,
            "battery_clear_of_traction_motors": min(battery_to_motor_clearances)
            >= battery["minimum_battery_to_heat_source_mm"],
            "battery_clear_of_wheels": min(battery_to_wheel_clearances)
            >= SPEC["minimum_clearances"]["moving_to_fixed"],
            "battery_clear_of_electronics_tray": battery_to_tray_clearance
            >= battery["minimum_battery_to_heat_source_mm"],
            "battery_clear_of_traction_childboard": battery_to_childboard_clearance
            >= battery["minimum_battery_to_heat_source_mm"],
            "battery_envelope_fits_chassis_and_enclosure": (
                abs(battery_limits[0][0]) <= chassis_half_width
                and abs(battery_limits[0][1]) <= chassis_half_width
                and abs(battery_limits[1][0]) <= chassis_half_depth
                and abs(battery_limits[1][1]) <= chassis_half_depth
                and battery_limits[2][0] >= SPEC["enclosure"]["wall"]
                and battery_limits[2][1] <= enclosure_inner_height
            ),
            "two_traction_motor_envelopes_declared": len(motors) == 2,
            "traction_motor_envelopes_are_symmetric": motor_positions_symmetric,
            "traction_motor_envelopes_fit_chassis_projection": all(
                abs(limit[0][0]) <= chassis_half_width
                and abs(limit[0][1]) <= chassis_half_width
                and abs(limit[1][0]) <= chassis_half_depth
                and abs(limit[1][1]) <= chassis_half_depth
                for limit in motor_limits
            ),
            "traction_childboard_fits_internal_envelope": (
                abs(childboard_limits[0][0]) <= enclosure_inner_half_width
                and abs(childboard_limits[0][1]) <= enclosure_inner_half_width
                and abs(childboard_limits[1][0]) <= enclosure_inner_half_depth
                and abs(childboard_limits[1][1]) <= enclosure_inner_half_depth
                and childboard_limits[2][0] >= SPEC["enclosure"]["wall"]
                and childboard_limits[2][1] + childboard["service_clearance_mm"] <= enclosure_inner_height
            ),
            "traction_childboard_clears_controller_service_volume": controller_to_childboard_clearance
            >= SPEC["minimum_clearances"]["pcb_to_shell"],
            "traction_childboard_mount_edge_margin_met": min(childboard_mount_edge_margins)
            >= childboard["minimum_mount_edge_margin_mm"],
            "traction_childboard_mount_support_reaches_envelope": abs(
                childboard_bottom_z - (support_top_z + support["standoff_height_mm"])
            )
            <= 0.01,
            "traction_childboard_rear_connector_corridor_met": rear_connector_corridor
            >= childboard["minimum_connector_corridor_mm"],
            "traction_motor_to_childboard_clearance_met": minimum_motor_to_childboard_clearance
            >= traction["minimum_motor_to_childboard_clearance_mm"],
        },
        "pcb_tray_margin_mm": [tray["width"] - pcb_width, tray["depth"] - pcb_depth],
        "pcb_edge_service_margin_mm": service_margin,
        "wheel_integration": {
            "status": wheel_spec["status"],
            "wheel_count": wheel_spec["count"],
            "wheel_envelope_mm": wheel_dimensions,
            "wheel_centres": wheel_centres,
            "wheelbase_mm": wheelbase,
            "track_mm": track,
            "maximum_chassis_side_overhang_mm": round(wheel_overhang_allowance, 1),
            "ground_contact_z_mm": round(min(limit[2][0] for limit in wheel_limits), 1),
            "release_blockers": wheel_spec["release_blockers"],
            "physical_validation": "NOT_EXECUTED",
        },
        "battery_integration": {
            "status": battery["status"],
            "reserved_envelope_mm": battery_dimensions,
            "xyz": battery["xyz"],
            "battery_to_motor_clearances_mm": [round(value, 1) for value in battery_to_motor_clearances],
            "battery_to_wheel_clearances_mm": [round(value, 1) for value in battery_to_wheel_clearances],
            "battery_to_tray_clearance_mm": round(battery_to_tray_clearance, 1),
            "battery_to_childboard_clearance_mm": round(battery_to_childboard_clearance, 1),
            "restraint": battery["restraint"],
            "release_blockers": battery["release_blockers"],
            "physical_validation": "NOT_EXECUTED",
        },
        "traction_integration": {
            "status": traction["status"],
            "architecture_scope": traction["architecture_scope"],
            "excluded_scope": traction["excluded_scope"],
            "motor_selection_status": traction["motor_selection_status"],
            "reserved_motor_envelope_mm": motor_dimensions,
            "motor_envelopes": motors,
            "childboard": childboard,
            "controller_to_childboard_clearance_mm": round(controller_to_childboard_clearance, 1),
            "rear_connector_corridor_mm": round(rear_connector_corridor, 1),
            "motor_to_childboard_clearances_mm": [round(value, 1) for value in motor_to_childboard_clearances],
            "minimum_motor_to_childboard_clearance_mm": round(minimum_motor_to_childboard_clearance, 1),
            "release_blockers": traction["release_blockers"],
            "physical_validation": "NOT_EXECUTED",
        },
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
    bracket_spec = SPEC["chassis"]["motor_bracket"]
    motor_bracket = (
        cq.Workplane("XY")
        .box(*bracket_spec["plate_envelope"])
        .faces(">Z")
        .workplane()
        .rect(*bracket_spec["mount_pattern"], forConstruction=True)
        .vertices()
        .hole(bracket_spec["mount_hole_diameter_mm"])
        .union(cq.Workplane("XZ").box(45, 28, 4).translate((0, -15.5, 14)))
    )
    traction = SPEC["traction_integration"]
    motor_dimensions = traction["reserved_motor_envelope"]
    motor_envelopes = {
        motor["id"]: cq.Workplane("XY").box(*motor_dimensions).translate(tuple(motor["xyz"]))
        for motor in traction["motor_envelopes"]
    }
    childboard = traction["childboard"]
    childboard_envelope = cq.Workplane("XY").box(*childboard["envelope"]).translate(tuple(childboard["xyz"]))
    support = childboard["mount_support"]
    support_plate = (
        cq.Workplane("XY")
        .box(childboard["envelope"][0], childboard["envelope"][1], support["plate_thickness_mm"])
        .faces(">Z")
        .workplane()
        .rect(*childboard["mount_pattern"], forConstruction=True)
        .vertices()
        .hole(support["mount_hole_diameter_mm"])
        .translate((childboard["xyz"][0], childboard["xyz"][1], support["plate_center_z_mm"]))
    )
    support_standoffs = [
        cq.Workplane("XY")
        .cylinder(support["standoff_height_mm"], support["standoff_diameter_mm"] / 2)
        .translate(
            (
                childboard["xyz"][0] + x_offset,
                childboard["xyz"][1] + y_offset,
                support["plate_center_z_mm"] + support["plate_thickness_mm"] / 2 + support["standoff_height_mm"] / 2,
            )
        )
        for x_offset in (-childboard["mount_pattern"][0] / 2, childboard["mount_pattern"][0] / 2)
        for y_offset in (-childboard["mount_pattern"][1] / 2, childboard["mount_pattern"][1] / 2)
    ]
    support_standoff_assembly = support_standoffs[0]
    for standoff in support_standoffs[1:]:
        support_standoff_assembly = support_standoff_assembly.union(standoff)
    wheel_spec = SPEC["chassis"]["wheels"]
    wheel_shapes = {
        wheel["id"]: cq.Workplane("XZ")
        .circle(wheel_spec["diameter_mm"] / 2)
        .extrude(wheel_spec["width_mm"] / 2, both=True)
        .translate(tuple(wheel["xyz"]))
        for wheel in wheel_spec["centres"]
    }
    battery = SPEC["battery_integration"]
    battery_envelope = cq.Workplane("XY").box(*battery["reserved_envelope_mm"]).translate(tuple(battery["xyz"]))

    parts = {
        "upper_shell": shell,
        "lower_chassis": chassis,
        "electronics_tray": tray,
        "display_bracket": display_bracket,
        "impact_bumper": bumper,
        "motor_bracket": motor_bracket,
        "traction_childboard_support": support_plate,
        "traction_childboard_standoffs": support_standoff_assembly,
    }
    part_dir = OUT / "parts"
    part_dir.mkdir(exist_ok=True)
    for name, shape in parts.items():
        part_path = part_dir / f"{name}.step"
        cq.exporters.export(shape, str(part_path), exportType="STEP")
        normalize_step(part_path)
    envelope_dir = OUT / "envelopes"
    envelope_dir.mkdir(exist_ok=True)
    envelope_shapes = {
        **motor_envelopes,
        childboard["id"]: childboard_envelope,
        "battery_pack_TBD": battery_envelope,
        **wheel_shapes,
    }
    for stale_path in envelope_dir.glob("*.step"):
        if stale_path.stem not in envelope_shapes:
            stale_path.unlink()
    for name, shape in envelope_shapes.items():
        envelope_path = envelope_dir / f"{name}.step"
        cq.exporters.export(shape, str(envelope_path), exportType="STEP")
        normalize_step(envelope_path)
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
    assembly.add(
        motor_envelopes["traction_motor_left"],
        name="traction_motor_left_TBD_envelope",
        color=cq.Color(0.9, 0.45, 0.05, 0.45),
    )
    assembly.add(
        motor_envelopes["traction_motor_right"],
        name="traction_motor_right_TBD_envelope",
        color=cq.Color(0.9, 0.45, 0.05, 0.45),
    )
    assembly.add(
        childboard_envelope, name="traction_driver_childboard_TBD_envelope", color=cq.Color(0.1, 0.55, 0.35, 0.45)
    )
    assembly.add(support_plate, name="traction_driver_childboard_support_TBD", color=cq.Color(0.5, 0.5, 0.5, 0.75))
    assembly.add(
        support_standoff_assembly,
        name="traction_driver_childboard_standoffs_TBD",
        color=cq.Color(0.35, 0.35, 0.35, 0.9),
    )
    assembly.add(battery_envelope, name="battery_pack_TBD_envelope", color=cq.Color(0.1, 0.25, 0.75, 0.45))
    for name, shape in wheel_shapes.items():
        assembly.add(shape, name=f"{name}_TBD_envelope", color=cq.Color(0.08, 0.08, 0.1, 0.55))
    assembly_path = OUT / "desk_robot_assembly.step"
    assembly.save(str(assembly_path), exportType="STEP")
    normalize_step(assembly_path)

    exploded = cq.Assembly(name="desk_robot_exploded")
    exploded.add(chassis.translate((0, 0, -30)), name="lower_chassis")
    exploded.add(tray.translate((0, 0, 45)), name="electronics_tray")
    exploded.add(shell.translate((0, 0, 130)), name="upper_shell")
    exploded.add(display_bracket.translate((0, -35, 180)), name="display_bracket")
    exploded.add(bumper.translate((0, 0, -70)), name="impact_bumper")
    exploded.add(motor_envelopes["traction_motor_left"].translate((0, 0, 15)), name="traction_motor_left_TBD_envelope")
    exploded.add(
        motor_envelopes["traction_motor_right"].translate((0, 0, 15)), name="traction_motor_right_TBD_envelope"
    )
    exploded.add(childboard_envelope.translate((0, 0, 80)), name="traction_driver_childboard_TBD_envelope")
    exploded.add(support_plate.translate((0, 0, 70)), name="traction_driver_childboard_support_TBD")
    exploded.add(support_standoff_assembly.translate((0, 0, 70)), name="traction_driver_childboard_standoffs_TBD")
    exploded.add(battery_envelope.translate((0, 0, -20)), name="battery_pack_TBD_envelope")
    for name, shape in wheel_shapes.items():
        exploded.add(shape.translate((0, 0, -15)), name=f"{name}_TBD_envelope")
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
    traction = SPEC["traction_integration"]
    motor_width, motor_depth, motor_height = traction["reserved_motor_envelope"]
    childboard = traction["childboard"]
    childboard_width, childboard_depth, childboard_height = childboard["envelope"]
    drawing_scale = 1.5
    top_x = 660
    top_y = 170
    wheel_spec = SPEC["chassis"]["wheels"]
    wheel_radius = wheel_spec["diameter_mm"] * drawing_scale / 2
    wheel_svg = "\n".join(
        f'<circle cx="{top_x + (wheel["xyz"][0] + width / 2) * drawing_scale:.1f}" '
        f'cy="{top_y + (wheel["xyz"][1] + depth / 2) * drawing_scale:.1f}" '
        f'r="{wheel_radius:.1f}" fill="#333" fill-opacity=".65" stroke="#111" stroke-width="2"/>'
        for wheel in wheel_spec["centres"]
    )
    left_motor = traction["motor_envelopes"][0]["xyz"]
    right_motor = traction["motor_envelopes"][1]["xyz"]
    left_motor_x = top_x + (left_motor[0] + width / 2 - motor_width / 2) * drawing_scale
    right_motor_x = top_x + (right_motor[0] + width / 2 - motor_width / 2) * drawing_scale
    motor_y = top_y + (left_motor[1] + depth / 2 - motor_depth / 2) * drawing_scale
    childboard_x = top_x + (childboard["xyz"][0] + width / 2 - childboard_width / 2) * drawing_scale
    childboard_y = top_y + (childboard["xyz"][1] + depth / 2 - childboard_depth / 2) * drawing_scale
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="760" viewBox="0 0 1200 760">
<style>text{{font-family:Arial,sans-serif;fill:#111}} .part{{fill:#e8edf2;stroke:#111;stroke-width:2}} .dim{{stroke:#1769aa;stroke-width:2;marker-start:url(#a);marker-end:url(#a)}} .note{{font-size:18px}} .tbd-motor{{fill:#f6b26b;fill-opacity:.55;stroke:#b45f06;stroke-width:2;stroke-dasharray:8 5}} .tbd-board{{fill:#93c47d;fill-opacity:.55;stroke:#38761d;stroke-width:2;stroke-dasharray:8 5}}</style>
<defs><marker id="a" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M8,0 L0,4 L8,8" fill="none" stroke="#1769aa"/></marker></defs>
<text x="40" y="45" font-size="28" font-weight="bold">Workbench-1 General Arrangement - mm - REV B</text>
<rect class="part" x="90" y="120" width="{width * 1.5}" height="{height * 1.5}" rx="27"/>
<rect x="187" y="450" width="225" height="108" fill="#20252b" stroke="#111" stroke-width="2"/>
<line class="dim" x1="90" y1="90" x2="510" y2="90"/><text x="280" y="80" class="note">{width}</text>
<line class="dim" x1="55" y1="120" x2="55" y2="615"/><text x="12" y="375" class="note" transform="rotate(-90 12 375)">{height}</text>
<text x="120" y="650" class="note">Front: display cutout 150 x 72; nominal wall 2.5</text>
<rect class="part" x="660" y="170" width="{width * 1.5}" height="{depth * 1.5}" rx="27"/>
<line class="dim" x1="660" y1="140" x2="1080" y2="140"/><text x="850" y="130" class="note">{width}</text>
<line class="dim" x1="1120" y1="170" x2="1120" y2="530"/><text x="1140" y="370" class="note" transform="rotate(-90 1140 370)">{depth}</text>
<rect x="675" y="185" width="390" height="330" fill="none" stroke="#e65c00" stroke-width="12" rx="24"/>
{wheel_svg}
<rect class="tbd-motor" x="{left_motor_x}" y="{motor_y}" width="{motor_width * drawing_scale}" height="{motor_depth * drawing_scale}"/><text x="{left_motor_x + 7}" y="{motor_y + 58}" font-size="14">LEFT MOTOR TBD</text>
<rect class="tbd-motor" x="{right_motor_x}" y="{motor_y}" width="{motor_width * drawing_scale}" height="{motor_depth * drawing_scale}"/><text x="{right_motor_x + 5}" y="{motor_y + 58}" font-size="14">RIGHT MOTOR TBD</text>
<rect class="tbd-board" x="{childboard_x}" y="{childboard_y}" width="{childboard_width * drawing_scale}" height="{childboard_depth * drawing_scale}"/><text x="{childboard_x + 10}" y="{childboard_y + 66}" font-size="15">DRIVER CHILDBOARD TBD</text>
<text x="700" y="565" class="note">8 TPU skin over 24 effective compliant stroke</text>
<text x="660" y="605" class="note">4 wheels dia {wheel_spec["diameter_mm"]} x {wheel_spec["width_mm"]}; 2x motor {motor_width} x {motor_depth} x {motor_height}; childboard {childboard_width} x {childboard_depth} x {childboard_height}</text>
<text x="660" y="640" class="note">CG Z={report["center_of_gravity_mm"][2]}; static tip angle={report["static_tip_angle_deg"]} deg</text>
<text x="660" y="675" class="note">Dashed geometry is TBD space claim only; physical fit and motor selection required</text>
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
<text x="300" y="350" font-size="20">60 mm fan; lower-front to upper-rear; traction childboard heat load remains TBD</text>
</svg>"""
    (drawings / "thermal-flow.svg").write_text(thermal, encoding="utf-8", newline="\n")
    fea = {
        "method": "energy and equivalent-static screening; nonlinear FEA and physical drop remain required",
        "drop_force_n_at_35g": round(report["mass_kg"] * 35 * 9.80665, 1),
        "drop_energy_j": report["drop_energy_j"],
        "effective_stroke_mm": SPEC["impact"]["effective_absorber_stroke_mm"],
        "estimated_bumper_contact_area_mm2": 18000,
        "estimated_average_compressive_stress_mpa": round(report["mass_kg"] * 35 * 9.80665 / 18000, 3),
        "acceptance": {
            "peak_deceleration_g": 35,
            "no_battery_contact": "PHYSICAL_VALIDATION_REQUIRED",
            "no_battery_contact_analytical": report["checks"]["battery_envelope_fits_chassis_and_enclosure"],
            "no_sharp_shell_fracture": "PHYSICAL_VALIDATION_REQUIRED",
        },
    }
    (OUT / "drop-screening.json").write_text(json.dumps(fea, indent=2) + "\n", encoding="utf-8")
    sequence = [
        {"step": 10, "part": "lower_chassis", "fastener": "fixture datum A"},
        {"step": 20, "part": "motor_brackets", "fastener": "8x M3x8 @ 0.55 Nm"},
        {
            "step": 25,
            "part": "left_and_right_traction_motors",
            "fastener": "TBD_BY_APPROVED_MOTOR",
            "status": "BLOCKED_MOTOR_SELECTION_AND_PHYSICAL_FIT",
        },
        {
            "step": 27,
            "part": "four_wheel_hub_and_tyre_assemblies",
            "fastener": "TBD_BY_APPROVED_WHEEL_AND_HUB",
            "status": "BLOCKED_WHEEL_SELECTION_LOAD_AND_SWEEP_VALIDATION",
        },
        {"step": 30, "part": "electronics_tray", "fastener": "4x M3x8 @ 0.55 Nm"},
        {
            "step": 35,
            "part": "traction_driver_childboard",
            "fastener": "TBD_BY_APPROVED_CHILDBOARD",
            "status": "BLOCKED_FINAL_OUTLINE_THERMAL_AND_CONNECTOR_FREEZE",
        },
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
        ["ME-001", "Lower chassis", "5052-H32 aluminium", 1, "ENGINEERING_BASELINE"],
        ["ME-002", "Upper shell", "PC-ABS FR", 1, "ENGINEERING_BASELINE"],
        ["ME-003", "Impact bumper", "TPU 95A", 1, "ENGINEERING_BASELINE"],
        ["ME-004", "Electronics tray", "5052-H32 aluminium", 1, "ENGINEERING_BASELINE"],
        ["ISO4762-M3x8", "Socket screw", "A2-70 stainless", 16, "ENGINEERING_BASELINE"],
        ["DIN934-M3", "Hex nut", "A2 stainless", 16, "ENGINEERING_BASELINE"],
        [
            "TBD_MOTOR_BRACKET",
            "Two motor bracket envelopes with provisional 35 x 25 mm mount pattern",
            "6061-T6 aluminium",
            2,
            "DO_NOT_ORDER_MOTOR_INTERFACE_REQUIRED",
        ],
        ["ME-006", "Display bracket", "PC-ABS FR", 1, "ENGINEERING_BASELINE"],
        [
            "TBD_WHEEL_HUB_TYRE_ASSEMBLY",
            "Four wheel envelopes at controlled wheelbase and track; hub, tyre, bearing and fastener TBD",
            "TBD_NOT_SELECTED",
            4,
            "DO_NOT_ORDER_SELECTION_AND_LOAD_VALIDATION_REQUIRED",
        ],
        [
            "TBD_TRACTION_MOTOR_MPN",
            "Traction motor reserved envelope only; technology, shaft, mount and MPN TBD",
            "TBD_NOT_SELECTED",
            2,
            "DO_NOT_ORDER_SELECTION_REQUIRED",
        ],
        [
            "TBD_TRACTION_DRIVER_CHILDBOARD",
            "Independent traction driver childboard reserved envelope only",
            "TBD_FINAL_ASSEMBLY",
            1,
            "DO_NOT_ORDER_OUTLINE_THERMAL_AND_CONNECTOR_FREEZE_REQUIRED",
        ],
        [
            "TBD_TRACTION_CHILDBOARD_SUPPORT",
            "Childboard support plate and four standoffs; datum and retention TBD",
            "TBD_FINAL_ASSEMBLY",
            1,
            "DO_NOT_ORDER_MOUNT_AND_SHOCK_RETENTION_REQUIRED",
        ],
        [
            "TBD_BATTERY_PACK_AND_RESTRAINT",
            "Battery reserved envelope and impact restraint; pack, BMS, disconnect and bracket TBD",
            "TBD_NOT_SELECTED",
            1,
            "DO_NOT_ORDER_PACK_AND_RESTRAINT_REQUIRED",
        ],
    ]
    with (OUT / "bom.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["part_number", "description", "material", "quantity", "release_status"])
        writer.writerows(rows)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
