# ruff: noqa: E501

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "full-system-structure.json").read_text(encoding="utf-8"))
OUT = ROOT / "generated" / "full_system"
STEP_EXPORT_TIMESTAMP = "2026-08-06T00:00:00"


def box_clearance(first: dict[str, list[float]], second: dict[str, list[float]]) -> float:
    gaps = [
        abs(first["xyz"][axis] - second["xyz"][axis]) - (first["dimensions"][axis] + second["dimensions"][axis]) / 2
        for axis in range(3)
    ]
    positive = [gap for gap in gaps if gap >= 0]
    return min(positive) if positive else max(gaps)


def load_mass_case() -> dict[str, object]:
    with (ROOT / "full-system-mass-ledger.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    mass = sum(float(row["mass_kg"]) for row in rows)
    cg = [sum(float(row["mass_kg"]) * float(row[f"{axis}_mm"]) for row in rows) / mass for axis in ("x", "y", "z")]
    return {
        "mass_kg": round(mass, 1),
        "center_of_gravity_mm": [round(value, 1) for value in cg],
        "row_count": len(rows),
        "all_rows_are_unmeasured_or_supplier_values": all(row["status"] != "MEASURED" for row in rows),
    }


def analyse() -> dict[str, object]:
    mass_case = load_mass_case()
    mass = float(mass_case["mass_kg"])
    cg = mass_case["center_of_gravity_mm"]
    mobility = SPEC["mobility"]
    feet = mobility["leveling_foot_centres_xy_mm"]
    support_span_x = max(point[0] for point in feet) - min(point[0] for point in feet)
    support_span_y = max(point[1] for point in feet) - min(point[1] for point in feet)
    roll_tip = math.degrees(math.atan2(support_span_x / 2 - abs(cg[0]), cg[2]))
    pitch_tip = math.degrees(math.atan2(support_span_y / 2 - abs(cg[1]), cg[2]))
    arm_mounts = SPEC["arm_mounts"]
    plate = arm_mounts["plate_mm"]
    pattern = arm_mounts["reserved_max_hole_pattern_span_mm"]
    hole_radius = arm_mounts["reserved_max_hole_diameter_mm"] / 2
    edge_ligaments = [(plate[axis] - pattern[axis]) / 2 - hole_radius for axis in range(2)]
    mount_positions = [mount["base_xyz_mm"] for mount in arm_mounts["mounts"]]
    arm_base_separation = math.dist(mount_positions[0][:2], mount_positions[1][:2])
    lower_bay = SPEC["lower_bay"]
    battery = {
        "dimensions": lower_bay["battery_reserved_envelope_mm"],
        "xyz": lower_bay["battery_reserved_xyz_mm"],
    }
    cabinets = [
        {"dimensions": cabinet["envelope_mm"], "xyz": cabinet["xyz_mm"]} for cabinet in lower_bay["controller_cabinets"]
    ]
    battery_clearances = [box_clearance(battery, cabinet) for cabinet in cabinets]
    deck_top = SPEC["frame"]["deck_top_z_mm"]
    mount_z_matches_deck = all(abs(position[2] - deck_top) <= 0.01 for position in mount_positions)
    design_factor = 1.5
    required_caster_rating = mass * design_factor / 2
    required_foot_rating = mass * design_factor / 3
    lift = SPEC["lift"]
    drive = SPEC["powered_mobility"]
    lift_range = lift["deck_top_max_z_mm"] - lift["deck_top_min_z_mm"]
    required_actuator_rating = mass * design_factor / 3
    slope_radians = math.radians(drive["design_floor_slope_deg"])
    tractive_force = (
        mass * 9.80665 * (drive["rolling_resistance_coefficient"] + math.sin(slope_radians))
        + mass * drive["maximum_commanded_acceleration_mps2"]
    )
    required_drive_torque = (
        tractive_force * (drive["drive_wheel_diameter_mm"] / 2000) / 2 * drive["traction_design_factor"]
    )
    required_brake_torque = (
        mass
        * 9.80665
        * math.sin(slope_radians)
        * (drive["drive_wheel_diameter_mm"] / 2000)
        / 2
        * drive["traction_design_factor"]
    )
    checks = {
        "two_arm_mounts_declared": arm_mounts["quantity"] == 2 and len(mount_positions) == 2,
        "arm_mounts_are_symmetric": mount_positions[0][0] == -mount_positions[1][0]
        and mount_positions[0][1:] == mount_positions[1][1:],
        "arm_mounts_land_on_deck": mount_z_matches_deck,
        "seven_axis_arms_declared": arm_mounts["joint_count"] == 7,
        "arm_mount_reserved_edge_ligament_met": min(edge_ligaments) >= arm_mounts["minimum_reserved_edge_ligament_mm"],
        "arm_bases_have_install_clearance": arm_base_separation >= plate[0] + 100,
        "operating_support_is_not_casters": mobility["transport_only_on_casters"]
        and "LEVELING" in mobility["operating_support"],
        "static_tip_angle_target_met_analytically": min(roll_tip, pitch_tip)
        >= mobility["minimum_static_tip_angle_deg"],
        "caster_rating_allocation_met": mobility["minimum_caster_rating_kg_each"] >= required_caster_rating,
        "leveling_foot_rating_allocation_met": mobility["minimum_leveling_foot_rating_kg_each"] >= required_foot_rating,
        "lift_stroke_is_consistent": lift_range == lift["stroke_mm"] and lift["stroke_mm"] > 0,
        "lift_has_redundant_limits_feedback_and_locks": lift["redundant_upper_and_lower_limit_switches"]
        and lift["absolute_position_feedback_each_column"]
        and lift["anti_drop_mechanical_locks_required"],
        "lift_and_arm_motion_are_interlocked": lift["arms_stowed_and_disabled_during_lift"]
        and lift["lift_enable_requires_feet_loaded"]
        and lift["motion_enable_requires_locks_engaged"],
        "lift_actuator_static_allocation_met": lift["minimum_actuator_static_rating_kg_each"]
        >= required_actuator_rating,
        "full_system_drive_is_not_controller_j2_childboard": drive["separate_protected_48v_branch_required"]
        and drive["controller_j2_power_prohibited"],
        "drive_torque_allocation_met": drive["minimum_continuous_output_torque_nm_each"] >= required_drive_torque,
        "drive_brake_allocation_met": drive["minimum_fail_safe_brake_torque_nm_each"] >= required_brake_torque,
        "transport_and_arm_motion_are_interlocked": drive["motion_requires_platform_lower_limit"]
        and drive["motion_requires_arms_stowed_and_disabled"]
        and drive["motion_requires_outriggers_retracted"]
        and drive["arm_enable_requires_drive_brakes_applied"],
        "battery_controller_clearance_met": min(battery_clearances)
        >= lower_bay["minimum_battery_to_controller_clearance_mm"],
        "power_signal_separation_is_defined": SPEC["cable_management"]["minimum_power_signal_separation_mm"] >= 50,
        "service_access_is_defined": all(
            SPEC["service"][key] >= 600
            for key in ("minimum_front_access_mm", "minimum_rear_access_mm", "minimum_side_access_mm")
        ),
        "mass_case_is_explicitly_unmeasured": mass_case["all_rows_are_unmeasured_or_supplier_values"],
        "supplier_and_physical_gates_remain_open": bool(SPEC["release_blockers"]) and "REQUIRED" in SPEC["status"],
    }
    return {
        "schema_version": SPEC["schema_version"],
        "configuration_id": SPEC["configuration_id"],
        "status": SPEC["status"],
        "engineering_package_pass": all(checks.values()),
        "checks": checks,
        "mass_case": mass_case,
        "support_polygon_mm": [support_span_x, support_span_y],
        "static_tip_angles_deg": {"roll": round(roll_tip, 1), "pitch": round(pitch_tip, 1)},
        "stability_case": "MAXIMUM_LIFT_ESTIMATED_MASS_AND_CG_NOT_MEASURED",
        "arm_mount": {
            "base_separation_mm": round(arm_base_separation, 1),
            "hole_edge_ligaments_mm": [round(value, 1) for value in edge_ligaments],
            "supplier_pattern_status": arm_mounts["supplier_drawing_gate"],
        },
        "load_allocations": {
            "design_factor": design_factor,
            "required_caster_rating_kg_each_two_caster_case": round(required_caster_rating, 1),
            "specified_caster_rating_kg_each": mobility["minimum_caster_rating_kg_each"],
            "required_leveling_foot_rating_kg_each_three_foot_case": round(required_foot_rating, 1),
            "specified_leveling_foot_rating_kg_each": mobility["minimum_leveling_foot_rating_kg_each"],
            "required_lift_actuator_rating_kg_each_three_actuator_case": round(required_actuator_rating, 1),
            "specified_lift_actuator_rating_kg_each": lift["minimum_actuator_static_rating_kg_each"],
        },
        "lift": {
            "deck_top_range_mm": [lift["deck_top_min_z_mm"], lift["deck_top_max_z_mm"]],
            "stroke_mm": lift["stroke_mm"],
            "maximum_column_skew_mm": lift["maximum_column_skew_mm"],
            "mechanical_lock_positions_mm": lift["mechanical_lock_positions_mm"],
        },
        "powered_mobility": {
            "calculated_required_drive_torque_nm_each": round(required_drive_torque, 1),
            "specified_continuous_drive_torque_nm_each": drive["minimum_continuous_output_torque_nm_each"],
            "calculated_required_brake_torque_nm_each": round(required_brake_torque, 1),
            "specified_fail_safe_brake_torque_nm_each": drive["minimum_fail_safe_brake_torque_nm_each"],
            "power_class_w_each": drive["motor_power_class_w_each"],
            "nominal_bus_voltage_v": drive["nominal_bus_voltage_v"],
        },
        "battery_to_controller_clearances_mm": [round(value, 1) for value in battery_clearances],
        "release_blockers": SPEC["release_blockers"],
        "note": "Digital geometry and load allocation are engineering screens only. The mass and CG use the maximum-lift design case. The compact 12 V Pololu/DRV8962 traction childboard is not approved to propel this full-size chassis. Vendor drawings, 48 V drive selection, lift safety validation, FEA, proof load, stability, collision sweep, bonding, and physical fit remain release gates.",
    }


def normalize_step(path: Path) -> None:
    text = "\n".join(line.rstrip() for line in path.read_text(encoding="ascii").splitlines()) + "\n"
    text = re.sub(
        r"(FILE_NAME\('[^']*',)'[^']*'",
        lambda match: f"{match.group(1)}'{STEP_EXPORT_TIMESTAMP}'",
        text,
        count=1,
    )
    path.write_text(text, encoding="ascii", newline="\n")


def _union(shapes):
    result = shapes[0]
    for shape in shapes[1:]:
        result = result.union(shape)
    return result


def _box(cq, dimensions, xyz):
    return cq.Workplane("XY").box(*dimensions).translate(tuple(xyz))


def _rhs(cq, length: float, cross_a: float, cross_b: float, wall: float, axis: str, xyz):
    dimensions = {
        "X": [length, cross_a, cross_b],
        "Y": [cross_a, length, cross_b],
        "Z": [cross_a, cross_b, length],
    }[axis]
    inner = dimensions.copy()
    length_axis = {"X": 0, "Y": 1, "Z": 2}[axis]
    inner[length_axis] += 2
    for index in range(3):
        if index != length_axis:
            inner[index] -= 2 * wall
    return _box(cq, dimensions, xyz).cut(_box(cq, inner, xyz))


def build_cad() -> bool:
    try:
        import cadquery as cq
    except ImportError:
        return False

    frame = SPEC["frame"]
    rail_w, rail_h, rail_wall = frame["rail_profile_mm"]
    fixed_w, fixed_d, fixed_wall = frame["fixed_column_profile_mm"]
    moving_w, moving_d, moving_wall = frame["moving_column_profile_mm"]
    deck_w, deck_d, deck_t = frame["deck_mm"]
    rail_x = deck_w - 160
    rail_y = deck_d - 160
    lower_z = frame["lower_frame_center_z_mm"]
    upper_z = frame["upper_frame_center_z_mm"]
    lower_members = []
    upper_members = []
    for y in (-rail_y / 2, rail_y / 2):
        lower_members.append(_rhs(cq, rail_x, rail_w, rail_h, rail_wall, "X", [0, y, lower_z]))
        upper_members.append(_rhs(cq, rail_x, rail_w, rail_h, rail_wall, "X", [0, y, upper_z]))
    for x in (-rail_x / 2, rail_x / 2):
        lower_members.append(_rhs(cq, rail_y, rail_w, rail_h, rail_wall, "Y", [x, 0, lower_z]))
        upper_members.append(_rhs(cq, rail_y, rail_w, rail_h, rail_wall, "Y", [x, 0, upper_z]))
    fixed_height = 420
    moving_height = 400
    lift_shapes = []
    for x, y in frame["column_centres_xy_mm"]:
        lower_members.append(_rhs(cq, fixed_height, fixed_w, fixed_d, fixed_wall, "Z", [x, y, 390]))
        upper_members.append(_rhs(cq, moving_height, moving_w, moving_d, moving_wall, "Z", [x, y, 500]))
        actuator = cq.Workplane("XY").cylinder(420, 22).translate((x, y, 390))
        lock_block = _box(cq, [130, 130, 24], [x, y, 610])
        lift_shapes.append(actuator.union(lock_block))
    for y in frame["crossmember_y_mm"]:
        upper_members.append(_rhs(cq, rail_x, rail_w, rail_h, rail_wall, "X", [0, y, upper_z]))
    fixed_base_frame = _union(lower_members)
    moving_upper_frame = _union(upper_members)
    lift_column_mechanisms = _union(lift_shapes)

    deck_center_z = frame["deck_top_z_mm"] - deck_t / 2
    deck = _box(cq, [deck_w, deck_d, deck_t], [0, 0, deck_center_z])
    arm = SPEC["arm_mounts"]
    plate_w, plate_d, plate_t = arm["plate_mm"]
    mount_plates = {}
    for mount in arm["mounts"]:
        x, y, z = mount["base_xyz_mm"]
        plate = cq.Workplane("XY").box(plate_w, plate_d, plate_t).translate((x, y, z + plate_t / 2))
        mount_plates[mount["id"]] = plate

    lower = SPEC["lower_bay"]
    battery_tray = _box(cq, lower["battery_ballast_tray_mm"], lower["battery_ballast_tray_xyz_mm"])
    battery_envelope = _box(cq, lower["battery_reserved_envelope_mm"], lower["battery_reserved_xyz_mm"])
    cabinet_envelopes = {
        cabinet["id"]: _box(cq, cabinet["envelope_mm"], cabinet["xyz_mm"]) for cabinet in lower["controller_cabinets"]
    }

    cable = SPEC["cable_management"]
    rear_tray = _box(cq, cable["rear_tray_mm"], cable["rear_tray_xyz_mm"])
    risers = [_box(cq, cable["arm_riser_tray_mm"], [mount["base_xyz_mm"][0], 330, 460]) for mount in arm["mounts"]]
    cable_management = _union([rear_tray, *risers])

    mobility = SPEC["mobility"]
    caster_shapes = []
    for x, y in mobility["caster_centres_xy_mm"]:
        wheel = (
            cq.Workplane("YZ")
            .circle(mobility["caster_wheel_diameter_mm"] / 2)
            .extrude(18, both=True)
            .translate((x, y, mobility["caster_wheel_diameter_mm"] / 2))
        )
        fork = _box(cq, [50, 50, 60], [x, y, mobility["caster_wheel_diameter_mm"] + 30])
        caster_shapes.append(wheel.union(fork))
    caster_assembly = _union(caster_shapes)
    drive = SPEC["powered_mobility"]
    drive_envelopes = {}
    for x, y, z in drive["drive_wheel_centres_xyz_mm"]:
        side = "left" if x < 0 else "right"
        wheel = (
            cq.Workplane("YZ")
            .circle(drive["drive_wheel_diameter_mm"] / 2)
            .extrude(drive["drive_wheel_width_mm"], both=True)
            .translate((x, y, z))
        )
        motor_x = x + (130 if x < 0 else -130)
        motor = _box(cq, drive["motor_envelope_mm_each"], [motor_x, y, z + 40])
        drive_envelopes[f"full_system_drive_{side}"] = wheel.union(motor)
    foot_shapes = []
    for x, y in mobility["leveling_foot_centres_xy_mm"]:
        pad = cq.Workplane("XY").cylinder(12, mobility["leveling_foot_pad_diameter_mm"] / 2).translate((x, y, 6))
        stem = cq.Workplane("XY").cylinder(150, 12).translate((x, y, 75))
        anchor_x = 500 if x > 0 else -500
        anchor_y = 300 if y > 0 else -300
        outrigger = _box(
            cq, [abs(x - anchor_x) + 80, abs(y - anchor_y) + 80, 50], [(x + anchor_x) / 2, (y + anchor_y) / 2, 150]
        )
        foot_shapes.append(pad.union(stem).union(outrigger))
    leveling_feet = _union(foot_shapes)

    guards = SPEC["guards"]
    bumper_w, bumper_d, bumper_h = guards["perimeter_bumper_mm"]
    bumper_outer = _box(cq, [bumper_w, bumper_d, bumper_h], [0, 0, guards["perimeter_bumper_center_z_mm"]])
    bumper_inner = _box(
        cq, [bumper_w - 40, bumper_d - 40, bumper_h + 4], [0, 0, guards["perimeter_bumper_center_z_mm"]]
    )
    perimeter_bumper = bumper_outer.cut(bumper_inner)

    arm_envelopes = {}
    for mount in arm["mounts"]:
        x, y, z = mount["base_xyz_mm"]
        side = -1 if x < 0 else 1
        base = cq.Workplane("XY").cylinder(170, 80).translate((x, y, z + 85))
        shoulder = cq.Workplane("XY").cylinder(300, 75).translate((x, y, z + 360))
        upper = cq.Workplane("XZ").circle(68).extrude(220, both=True).translate((x, y + 220, z + 520))
        elbow = cq.Workplane("XY").cylinder(260, 64).translate((x + side * 90, y + 440, z + 680))
        forearm = cq.Workplane("XZ").circle(58).extrude(180, both=True).translate((x + side * 90, y + 600, z + 820))
        redundant_joint = cq.Workplane("XY").cylinder(180, 54).translate((x + side * 140, y + 700, z + 950))
        wrist = cq.Workplane("XY").cylinder(140, 48).translate((x + side * 140, y + 700, z + 1100))
        tool = _box(cq, arm["tool_envelope_mm"], [x + side * 140, y + 700, z + 1300])
        arm_envelopes[mount["id"]] = _union([base, shoulder, upper, elbow, forearm, redundant_joint, wrist, tool])

    parts = {
        "fixed_chassis_frame": fixed_base_frame,
        "moving_upper_frame": moving_upper_frame,
        "lift_column_mechanisms": lift_column_mechanisms,
        "worktop_deck": deck,
        "arm_mount_plate_left": mount_plates["left_arm"],
        "arm_mount_plate_right": mount_plates["right_arm"],
        "battery_ballast_tray": battery_tray,
        "cable_management": cable_management,
        "caster_assembly": caster_assembly,
        "leveling_feet": leveling_feet,
        "perimeter_bumper": perimeter_bumper,
    }
    envelopes = {
        "battery_pack_TBD": battery_envelope,
        **cabinet_envelopes,
        **arm_envelopes,
        **drive_envelopes,
    }
    part_dir = OUT / "parts"
    envelope_dir = OUT / "envelopes"
    part_dir.mkdir(parents=True, exist_ok=True)
    envelope_dir.mkdir(parents=True, exist_ok=True)
    for directory, shapes in ((part_dir, parts), (envelope_dir, envelopes)):
        expected = {f"{name}.step" for name in shapes}
        for stale in directory.glob("*.step"):
            if stale.name not in expected:
                stale.unlink()
        for name, shape in shapes.items():
            path = directory / f"{name}.step"
            cq.exporters.export(shape, str(path), exportType="STEP")
            normalize_step(path)

    assembly = cq.Assembly(name="dual_7dof_lifting_workbench")
    for name, shape in {**parts, **envelopes}.items():
        assembly.add(shape, name=name)
    assembly_path = OUT / "full_system_assembly.step"
    assembly.save(str(assembly_path), exportType="STEP")
    normalize_step(assembly_path)

    lift_delta = SPEC["lift"]["stroke_mm"]
    moving_names = {
        "moving_upper_frame",
        "worktop_deck",
        "arm_mount_plate_left",
        "arm_mount_plate_right",
        "cable_management",
        "left_arm",
        "right_arm",
    }
    max_lift = cq.Assembly(name="dual_7dof_lifting_workbench_max_lift")
    for name, shape in {**parts, **envelopes}.items():
        max_lift.add(shape.translate((0, 0, lift_delta)) if name in moving_names else shape, name=name)
    max_lift_path = OUT / "full_system_max_lift.step"
    max_lift.save(str(max_lift_path), exportType="STEP")
    normalize_step(max_lift_path)

    exploded = cq.Assembly(name="dual_7dof_lifting_workbench_exploded")
    exploded.add(fixed_base_frame, name="fixed_chassis_frame")
    exploded.add(moving_upper_frame.translate((0, 0, 120)), name="moving_upper_frame")
    exploded.add(lift_column_mechanisms.translate((0, 0, -60)), name="lift_column_mechanisms")
    exploded.add(deck.translate((0, 0, 180)), name="worktop_deck")
    exploded.add(mount_plates["left_arm"].translate((-80, 0, 260)), name="arm_mount_plate_left")
    exploded.add(mount_plates["right_arm"].translate((80, 0, 260)), name="arm_mount_plate_right")
    exploded.add(battery_tray.translate((0, 80, -80)), name="battery_ballast_tray")
    exploded.add(battery_envelope.translate((0, 120, -40)), name="battery_pack_TBD")
    exploded.add(cable_management.translate((0, 120, 100)), name="cable_management")
    exploded.add(caster_assembly.translate((0, 0, -100)), name="caster_assembly")
    exploded.add(leveling_feet.translate((0, 0, -140)), name="leveling_feet")
    exploded.add(perimeter_bumper.translate((0, 0, -60)), name="perimeter_bumper")
    exploded.add(cabinet_envelopes["left_arm_controller"].translate((-80, 0, 0)), name="left_arm_controller")
    exploded.add(cabinet_envelopes["right_arm_controller"].translate((80, 0, 0)), name="right_arm_controller")
    exploded.add(arm_envelopes["left_arm"].translate((-120, 0, 340)), name="left_arm")
    exploded.add(arm_envelopes["right_arm"].translate((120, 0, 340)), name="right_arm")
    exploded.add(drive_envelopes["full_system_drive_left"].translate((-80, 0, -40)), name="full_system_drive_left")
    exploded.add(drive_envelopes["full_system_drive_right"].translate((80, 0, -40)), name="full_system_drive_right")
    exploded_path = OUT / "full_system_exploded.step"
    exploded.save(str(exploded_path), exportType="STEP")
    normalize_step(exploded_path)
    return True


def write_support_files(report: dict[str, object]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "analysis.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    sequence = [
        {"step": 10, "assembly": "fixed_chassis_frame", "gate": "weld map flatness and bond lands inspected"},
        {
            "step": 20,
            "assembly": "casters_deployable_outriggers_and_leveling_feet",
            "gate": "rated parts approved outriggers locked and all feet carry load",
        },
        {"step": 30, "assembly": "battery_ballast_tray", "gate": "pack restraint and service disconnect approved"},
        {
            "step": 40,
            "assembly": "arm_controller_cabinets",
            "gate": "ventilation connector and service access verified",
        },
        {
            "step": 50,
            "assembly": "guided_lift_columns_actuators_locks_upper_frame_and_deck",
            "gate": "skew limits redundant switches anti-drop locks proof load and deck survey attached",
        },
        {
            "step": 60,
            "assembly": "left_and_right_arm_mount_plates",
            "gate": "purchased-arm drawing and torque approved",
        },
        {
            "step": 70,
            "assembly": "seven_axis_vendor_arms",
            "gate": "rated lift fixture and supplier installation procedure required",
        },
        {
            "step": 80,
            "assembly": "cable_management_and_bonding",
            "gate": "full sweep bend radius and protective bond test",
        },
        {"step": 90, "assembly": "guards_and_bumpers", "gate": "pinch and site risk assessment closed"},
        {
            "step": 100,
            "assembly": "commissioning",
            "gate": "proof load stability pull and guarded dual-arm sweep executed",
        },
    ]
    (OUT / "assembly-sequence.json").write_text(json.dumps(sequence, indent=2) + "\n", encoding="utf-8", newline="\n")
    bom = [
        ["FS-001", "Fixed welded RHS chassis frame", "S355 steel", "1", "ENGINEERING_BASELINE_FEA_OPEN"],
        ["FS-001A", "Moving RHS upper frame", "S355 steel", "1", "ENGINEERING_BASELINE_FEA_OPEN"],
        [
            "TBD-LIFT",
            "Synchronized guided lift columns actuators locks feedback and limits",
            "supplier assemblies",
            "4",
            "MPN_SAFETY_AND_PROOF_LOAD_REQUIRED",
        ],
        [
            "FS-002",
            "Worktop/deck with two arm mount zones",
            "20 mm tooling plate",
            "1",
            "SUPPLIER_DRAWING_CONFIRMATION_REQUIRED",
        ],
        [
            "FS-003",
            "Undrilled seven-axis arm adapter plate",
            "S355 steel",
            "2",
            "NOMINAL_PATTERN_DO_NOT_FABRICATE_BEFORE_VENDOR_CONFIRMATION",
        ],
        ["FS-004", "Battery and ballast retention tray", "S355 steel", "1", "PACK_SELECTION_REQUIRED"],
        ["FS-005", "Rear and arm-riser cable trays", "galvanized steel", "1 set", "HARNESS_SWEEP_REQUIRED"],
        ["FS-006", "Perimeter bumper/toe guard", "steel plus elastomer", "1", "SITE_RISK_REVIEW_REQUIRED"],
        ["TBD-CASTER", "Swivel braked caster 300 kg minimum", "supplier assembly", "4", "MPN_AND_LOAD_RATING_REQUIRED"],
        [
            "TBD-DRIVE",
            "48 V 400 W geared drive wheel with fail-safe brake",
            "supplier assembly",
            "2",
            "MPN_CONTROLLER_BRAKE_AND_WHEEL_LOAD_VALIDATION_REQUIRED",
        ],
        [
            "TBD-FOOT",
            "Deployable outrigger and leveling foot 300 kg minimum",
            "supplier assembly",
            "4",
            "MPN_LOCK_AND_LOAD_RATING_REQUIRED",
        ],
        [
            "TBD-7DOF",
            "Medium-class seven-axis collaborative arm envelope",
            "vendor assembly",
            "2",
            "PURCHASED_REVISION_REQUIRED",
        ],
        [
            "TBD-CTRL",
            "Seven-axis arm controller cabinet envelope",
            "vendor assembly",
            "2",
            "PURCHASED_REVISION_FIT_REQUIRED",
        ],
        [
            "TBD-BATTERY",
            "Battery ballast BMS and service disconnect envelope",
            "supplier assembly",
            "1",
            "PACK_AND_RESTRAINT_REQUIRED",
        ],
    ]
    with (OUT / "bom.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["part_number", "description", "material", "quantity", "release_status"])
        writer.writerows(bom)

    drawings = OUT / "drawings"
    drawings.mkdir(exist_ok=True)
    cg_x, cg_y, cg_z = report["mass_case"]["center_of_gravity_mm"]
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="900" viewBox="0 0 1400 900">
<style>text{{font-family:Arial,sans-serif;fill:#111}} .frame{{fill:#d9e1e8;stroke:#263238;stroke-width:3}} .arm{{fill:#90a4ae;stroke:#37474f;stroke-width:3}} .tbd{{fill:#ffd180;stroke:#e65100;stroke-width:3;stroke-dasharray:9 6}} .dim{{stroke:#1565c0;stroke-width:2}}</style>
<text x="40" y="48" font-size="30" font-weight="bold">Dual 7-DOF Lifting Workbench - Structural General Arrangement - REV B</text>
<rect class="frame" x="80" y="160" width="600" height="400"/><rect class="frame" x="80" y="525" width="600" height="35"/>
<rect class="arm" x="185" y="120" width="125" height="125"/><rect class="arm" x="450" y="120" width="125" height="125"/>
<rect class="tbd" x="230" y="315" width="200" height="140"/><rect class="tbd" x="455" y="315" width="200" height="140"/>
<rect class="tbd" x="285" y="445" width="240" height="95"/>
<text x="185" y="110" font-size="18">LEFT 7-DOF MOUNT</text><text x="450" y="110" font-size="18">RIGHT 7-DOF MOUNT</text>
<text x="245" y="390" font-size="18">CONTROLLER</text><text x="480" y="390" font-size="18">CONTROLLER</text><text x="330" y="500" font-size="18">BATTERY / BALLAST</text>
<line class="dim" x1="80" y1="595" x2="680" y2="595"/><text x="350" y="620" font-size="20">1200 mm</text>
<text x="80" y="660" font-size="18">Top view: 1200 x 800 deck; arm bases +/-300 X, -150 Y; four deployable leveling outriggers.</text>
<rect class="frame" x="790" y="190" width="500" height="20"/><rect class="frame" x="825" y="210" width="35" height="380"/><rect class="frame" x="1220" y="210" width="35" height="380"/>
<rect class="arm" x="860" y="110" width="110" height="100"/><rect class="arm" x="1110" y="110" width="110" height="100"/>
<path class="arm" d="M915 110 L915 60 L1030 60 L1030 20" fill="none" stroke-width="42"/><path class="arm" d="M1165 110 L1165 60 L1050 60 L1050 20" fill="none" stroke-width="42"/>
<rect class="tbd" x="875" y="300" width="160" height="250"/><rect class="tbd" x="1045" y="300" width="160" height="250"/>
<circle cx="{1040 + cg_x * 0.4:.1f}" cy="{590 - cg_z * 0.4:.1f}" r="9" fill="#d32f2f"/><text x="1048" y="{590 - cg_z * 0.4:.1f}" font-size="17">estimated CG ({cg_x}, {cg_y}, {cg_z}) mm</text>
<text x="790" y="660" font-size="18">Side view: 750-1100 mm lift; max-height estimate {report["mass_case"]["mass_kg"]} kg; tip angles {report["static_tip_angles_deg"]["roll"]}/{report["static_tip_angles_deg"]["pitch"]} deg.</text>
<text x="80" y="730" font-size="18">Orange dashed items are supplier/TBD envelopes. Vendor arm geometry is not fabricated from this drawing.</text>
<text x="80" y="765" font-size="18">Release requires arm and lift vendor data, FEA, lift proof/skew tests, stability pull, bond test, guarded sweep, and service-fit evidence.</text>
</svg>'''
    (drawings / "general-arrangement.svg").write_text(svg, encoding="utf-8", newline="\n")


def main() -> int:
    report = analyse()
    OUT.mkdir(parents=True, exist_ok=True)
    if not report["engineering_package_pass"]:
        print(json.dumps(report, indent=2))
        return 1
    cad_exported = build_cad()
    report["cad_exported"] = cad_exported
    write_support_files(report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
