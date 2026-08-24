from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_generator():
    path = ROOT / "hardware/mechanical/tools/generate_artifacts.py"
    spec = importlib.util.spec_from_file_location("motor_mechanical_generator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_traction_envelopes_are_symmetric_and_fail_closed() -> None:
    spec = json.loads((ROOT / "hardware/mechanical/design-spec.json").read_text(encoding="utf-8"))
    traction = spec["traction_integration"]
    motors = traction["motor_envelopes"]

    assert traction["motor_selection_status"] == "TBD_NOT_SELECTED_DO_NOT_ORDER"
    assert "seven_axis_arm" in traction["excluded_scope"]
    assert {motor["side"] for motor in motors} == {"left", "right"}
    assert motors[0]["xyz"][0] == -motors[1]["xyz"][0]
    assert motors[0]["xyz"][1:] == motors[1]["xyz"][1:]
    wheels = spec["chassis"]["wheels"]
    assert spec["chassis"]["track_axis"] == "X"
    assert spec["chassis"]["wheelbase_axis"] == "Y"
    assert {tuple(wheel["xyz"][:2]) for wheel in wheels["centres"]} == {
        (-105, -90),
        (105, -90),
        (-105, 90),
        (105, 90),
    }
    assert len(traction["release_blockers"]) >= 5
    assert traction["childboard"]["selection_status"].startswith("TBD_")


def test_traction_geometry_checks_pass_without_claiming_physical_validation() -> None:
    report = load_generator().analyse()
    checks = report["checks"]
    traction = report["traction_integration"]

    assert all(checks.values())
    assert checks["two_traction_motor_envelopes_declared"]
    assert checks["traction_motor_envelopes_are_symmetric"]
    assert checks["traction_childboard_clears_controller_service_volume"]
    assert checks["traction_childboard_rear_connector_corridor_met"]
    assert checks["traction_motor_to_childboard_clearance_met"]
    assert checks["battery_clear_of_traction_motors"]
    assert checks["battery_clear_of_electronics_tray"]
    assert checks["battery_clear_of_traction_childboard"]
    assert checks["traction_childboard_mount_support_reaches_envelope"]
    assert checks["traction_childboard_mount_support_reaches_fixed_datum"]
    assert checks["traction_childboard_mount_support_height_is_positive"]
    assert checks["traction_childboard_mount_support_base_matches_tray"]
    assert checks["motor_bracket_base_contacts_chassis"]
    assert checks["motor_bracket_uprights_reach_motor_envelopes"]
    assert checks["wheel_axis_mapping_is_explicit"]
    assert traction["physical_validation"] == "NOT_EXECUTED"
    assert "PHYSICAL_VALIDATION_REQUIRED" in report["status"]
    assert traction["minimum_motor_to_childboard_clearance_mm"] >= 3
    assert traction["rear_connector_corridor_mm"] >= 20
    assert report["wheel_integration"]["wheelbase_mm"] == 180
    assert report["wheel_integration"]["track_mm"] == 210
    assert report["generated_datums"]["electronics_tray_bottom_z_mm"] == 99
    assert report["generated_datums"]["electronics_tray_top_z_mm"] == 102
    assert report["generated_datums"]["childboard_support_base_z_mm"] == 102
    assert report["generated_datums"]["childboard_support_base_top_z_mm"] == 134.5


def test_concept_drivetrain_pair_map_and_axes_are_auditable() -> None:
    spec = json.loads((ROOT / "hardware/mechanical/design-spec.json").read_text(encoding="utf-8"))
    drivetrain = spec["traction_integration"]["drivetrain"]
    assert drivetrain["architecture"] == "TWO_MOTOR_REAR_WHEEL_DIFFERENTIAL"
    assert set(drivetrain["driven_wheels"]) == {"wheel_rear_left", "wheel_rear_right"}
    assert set(drivetrain["passive_wheels"]) == {"wheel_front_left", "wheel_front_right"}
    assert all(
        item["motor_output"]["axis_direction"] == [1, 0, 0] and item["wheel_hub"]["axis_direction"] == [1, 0, 0]
        for item in drivetrain["motor_to_wheel_interfaces"]
    )
    assert {(item["motor_id"], item["wheel_id"]) for item in drivetrain["motor_to_wheel_interfaces"]} == {
        ("traction_motor_left", "wheel_rear_left"),
        ("traction_motor_right", "wheel_rear_right"),
    }
    assert drivetrain["physical_validation"] == "NOT_EXECUTED"


def test_lateral_axle_roll_vector_matches_declared_forward_direction() -> None:
    spec = json.loads((ROOT / "hardware/mechanical/design-spec.json").read_text(encoding="utf-8"))
    convention = spec["traction_integration"]["drivetrain"]["axis_convention"]
    assert convention["wheel_hub_axis_direction"] == [1, 0, 0]
    assert convention["ground_contact_radial_direction"] == [0, 0, -1]
    assert convention["forward_axis_direction"] == [0, -1, 0]
    assert convention["nominal_forward_hub_angular_velocity_direction"] == [-1, 0, 0]
    # omega x r at the floor contact is the chassis forward velocity direction.
    omega = convention["nominal_forward_hub_angular_velocity_direction"]
    radial = convention["ground_contact_radial_direction"]
    cross = [
        omega[1] * radial[2] - omega[2] * radial[1],
        omega[2] * radial[0] - omega[0] * radial[2],
        omega[0] * radial[1] - omega[1] * radial[0],
    ]
    assert cross == convention["forward_axis_direction"]


def test_scad_and_generated_report_share_battery_and_stability_baseline() -> None:
    scad = (ROOT / "hardware/mechanical/cad/desk_robot.scad").read_text(encoding="utf-8")
    assert "BATTERY_ENV = [80,100,40]" in scad
    assert "BATTERY_Y = 0" in scad
    assert "BATTERY_Z = 52" in scad
    assert "HUB_REAR_Y = 90" in scad
    assert "HUB_REAR_X = 105" in scad
    assert "CHASSIS_MOUNT_X = 121" in scad
    assert "CHASSIS_MOUNT_Y = 102.5" in scad
    assert "translate([30,37,99]) cube([220,170,3]);" in scad
    assert "WHEEL_TRACK_HALF = 105" in scad
    assert "WHEELBASE_HALF = 90" in scad
    assert "rotate([0,90,0])" in scad
    assert "traction_motor_bracket" in scad
    assert "traction_childboard_support" in scad
    assert "CHILDBOARD_Z = 151" in scad
    assert "CHILDBOARD_BASE_POST_H = 32.5" in scad
    report = json.loads((ROOT / "hardware/mechanical/generated/analysis.json").read_text(encoding="utf-8"))
    assert report["center_of_gravity_mm"] == [0.0, 1.7, 97.9]
    assert report["static_tip_angle_deg"] == 42.6
    assert report["static_tip_angles_deg"] == {"roll_about_y": 47.0, "pitch_about_x": 42.6}
    assert report["traction_integration"]["drivetrain"]["physical_validation"] == "NOT_EXECUTED"
    assert report["checks"]["traction_drivetrain_roll_direction_matches_forward"]
    assert report["checks"]["wheel_axial_clearance_within_tolerance"]
    assert report["checks"]["wheel_shell_radial_clearance_within_tolerance"]
    assert report["wheel_integration"]["wheel_shell_radial_clearance_mm"] >= 4.0
    assert report["wheel_integration"]["mount_to_wheel_ligament_mm"] >= 3.0
    assert report["wheel_integration"]["mount_to_well_cut_ligament_mm"] >= 3.0
    assert report["mass_cases"]["compact_enclosure"]["mass_kg"] == 6.42
    assert report["mass_cases"]["full_system"]["mass_kg"] == 55.0
    assert report["mass_cases"]["full_system"]["status"] == "ESTIMATE_NOT_MEASURED"


def test_generated_step_datums_match_fixed_mechanical_contacts() -> None:
    cadquery = pytest.importorskip("cadquery")

    def bounds(path: Path):
        shape = cadquery.importers.importStep(str(path))
        box = shape.val().BoundingBox()
        return tuple(round(value, 3) for value in (box.xmin, box.xmax, box.ymin, box.ymax, box.zmin, box.zmax))

    assert bounds(ROOT / "hardware/mechanical/generated/parts/electronics_tray.step")[4:] == (99.0, 102.0)
    lower_chassis = cadquery.importers.importStep(str(ROOT / "hardware/mechanical/generated/parts/lower_chassis.step"))
    assert len(lower_chassis.solids().vals()) == 1
    nominal_plate_volume = 260 * 220 * 4 - 4 * 3.141592653589793 * (4.2 / 2) ** 2 * 4
    assert lower_chassis.val().Volume() < nominal_plate_volume - 3000
    for wheel_path in sorted((ROOT / "hardware/mechanical/generated/envelopes").glob("wheel_*.step")):
        wheel = cadquery.importers.importStep(str(wheel_path))
        assert lower_chassis.val().intersect(wheel.val()).Volume() < 0.001
    assert bounds(ROOT / "hardware/mechanical/generated/parts/motor_bracket.step")[4:] == (0.0, 46.0)
    assert bounds(ROOT / "hardware/mechanical/generated/parts/traction_childboard_standoffs.step")[4:] == (
        102.0,
        141.0,
    )

    assembly = cadquery.importers.importStep(str(ROOT / "hardware/mechanical/generated/desk_robot_assembly.step"))
    assembly_boxes = [solid.BoundingBox() for solid in assembly.solids().vals()]
    assert any(abs(box.zmin - 26.0) < 0.001 and abs(box.zmax - 72.0) < 0.001 for box in assembly_boxes)
    assert any(abs(box.zmin - 102.0) < 0.001 and abs(box.zmax - 134.5) < 0.001 for box in assembly_boxes)


def test_generated_motor_and_childboard_envelopes_are_explicit_tbd_artifacts() -> None:
    envelope_dir = ROOT / "hardware/mechanical/generated/envelopes"
    expected = {
        "traction_motor_left.step",
        "traction_motor_right.step",
        "traction_driver_childboard.step",
        "battery_pack_TBD.step",
        "wheel_front_left.step",
        "wheel_front_right.step",
        "wheel_rear_left.step",
        "wheel_rear_right.step",
    }
    assert {path.name for path in envelope_dir.glob("*.step")} == expected
    for name in expected:
        content = (envelope_dir / name).read_text(encoding="ascii")
        assert content.startswith("ISO-10303-21;")
        assert "MANIFOLD_SOLID_BREP" in content

    with (ROOT / "hardware/mechanical/generated/bom.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    motor = next(row for row in rows if row["part_number"] == "TBD_TRACTION_MOTOR_MPN")
    childboard = next(row for row in rows if row["part_number"] == "TBD_TRACTION_DRIVER_CHILDBOARD")
    assert motor["quantity"] == "2"
    assert motor["release_status"] == "DO_NOT_ORDER_SELECTION_REQUIRED"
    assert childboard["release_status"].startswith("DO_NOT_ORDER_")

    wheel = next(row for row in rows if row["part_number"] == "TBD_WHEEL_HUB_TYRE_ASSEMBLY")
    battery = next(row for row in rows if row["part_number"] == "TBD_BATTERY_PACK_AND_RESTRAINT")
    assert wheel["quantity"] == "4"
    assert wheel["release_status"].startswith("DO_NOT_ORDER_")
    assert battery["quantity"] == "1"
    assert battery["release_status"].startswith("DO_NOT_ORDER_")


def test_mechanical_docs_keep_vendor_arm_and_physical_gates_explicit() -> None:
    readme = (ROOT / "hardware/mechanical/README.md").read_text(encoding="utf-8")
    integration = (ROOT / "hardware/mechanical/system-integration.md").read_text(encoding="utf-8")
    assert "fourteen joints" in readme
    assert "must not be ordered" in readme
    assert "vendor controller cabinet" in integration
    assert "not measured results" in integration
    assert "battery" in integration
    assert "standoff" in integration
