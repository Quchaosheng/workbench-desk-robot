from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "hardware/mechanical/tools"


def load_generator():
    path = TOOLS / "generate_full_system.py"
    spec = importlib.util.spec_from_file_location("full_system_mechanics", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_full_system_analysis_is_consistent_and_fail_closed() -> None:
    report = load_generator().analyse()
    assert report["engineering_package_pass"] is True
    assert report["configuration_id"] == "DUAL_7DOF_LIFTING_WORKBENCH_REV_C"
    assert report["schema_version"] == 2
    assert report["mass_case"]["mass_kg"] == 368.0
    assert report["mass_case"]["center_of_gravity_mm"] == [0.0, -28.8, 751.0]
    assert report["support_polygon_mm"] == [1200, 960]
    assert min(report["static_tip_angles_deg"].values()) >= 25
    assert report["stability_case"] == "MAXIMUM_LIFT_ESTIMATED_MASS_AND_CG_NOT_MEASURED"
    assert report["arm_mount"]["base_separation_mm"] == 600
    assert min(report["arm_mount"]["hole_edge_ligaments_mm"]) >= 46
    assert report["checks"]["seven_axis_arms_declared"] is True
    assert report["checks"]["lift_and_arm_motion_are_interlocked"] is True
    assert report["checks"]["lift_has_redundant_limits_feedback_and_locks"] is True
    assert report["checks"]["full_system_drive_is_not_controller_j2_childboard"] is True
    assert report["checks"]["drive_torque_allocation_met"] is True
    assert report["checks"]["drive_brake_allocation_met"] is True
    assert report["checks"]["transport_and_arm_motion_are_interlocked"] is True
    assert report["lift"]["deck_top_range_mm"] == [750, 1100]
    assert report["lift"]["stroke_mm"] == 350
    assert report["load_allocations"]["specified_caster_rating_kg_each"] == 300
    assert report["load_allocations"]["specified_lift_actuator_rating_kg_each"] == 300
    assert min(report["battery_to_controller_clearances_mm"]) >= 50
    assert report["release_blockers"]
    assert "REQUIRED" in report["status"]


def test_full_system_cad_package_contains_structures_and_supplier_envelopes() -> None:
    generated = ROOT / "hardware/mechanical/generated/full_system"
    assembly = generated / "full_system_assembly.step"
    max_lift = generated / "full_system_max_lift.step"
    exploded = generated / "full_system_exploded.step"
    assert assembly.stat().st_size > 500_000
    assert max_lift.stat().st_size > 500_000
    assert exploded.stat().st_size > 500_000
    text = assembly.read_text(encoding="ascii")
    assert "ISO-10303-21;" in text
    assert "'2026-08-06T00:00:00'" in text
    assert "'2026-08-06T00:00:00'" in exploded.read_text(encoding="ascii")
    assert "'2026-08-06T00:00:00'" in max_lift.read_text(encoding="ascii")
    assert len(list((generated / "parts").glob("*.step"))) == 11
    assert len(list((generated / "envelopes").glob("*.step"))) == 7
    for required in (
        "fixed_chassis_frame.step",
        "moving_upper_frame.step",
        "lift_column_mechanisms.step",
        "worktop_deck.step",
        "arm_mount_plate_left.step",
        "arm_mount_plate_right.step",
        "leveling_feet.step",
    ):
        assert (generated / "parts" / required).stat().st_size > 10_000
    for required in ("left_arm.step", "right_arm.step", "left_arm_controller.step", "right_arm_controller.step"):
        assert (generated / "envelopes" / required).stat().st_size > 10_000
    for required in ("full_system_drive_left.step", "full_system_drive_right.step"):
        assert (generated / "envelopes" / required).stat().st_size > 10_000


def test_full_system_outputs_do_not_claim_physical_validation() -> None:
    root = ROOT / "hardware/mechanical"
    spec = json.loads((root / "full-system-structure.json").read_text(encoding="utf-8"))
    report = json.loads((root / "generated/full_system/analysis.json").read_text(encoding="utf-8"))
    assert spec["frame"]["physical_validation"] == "NOT_EXECUTED"
    assert spec["lift"]["dynamic_and_physical_validation"] == "NOT_EXECUTED"
    assert spec["arm_mounts"]["joint_count"] == 7
    assert "UNDRILLED" in spec["arm_mounts"]["supplier_drawing_gate"]
    assert spec["cable_management"]["physical_sweep_validation"] == "NOT_EXECUTED"
    assert report["mass_case"]["all_rows_are_unmeasured_or_supplier_values"] is True
    assert report["release_blockers"] == spec["release_blockers"]


def test_prephysical_power_and_component_decisions_fail_closed() -> None:
    root = ROOT / "hardware"
    power = json.loads((root / "release/full-system-power-architecture.json").read_text(encoding="utf-8"))
    assert power["status"].endswith("VALIDATION_REQUIRED")
    assert power["battery_bus"]["minimum_energy_wh"] >= 2000
    assert power["battery_bus"]["minimum_continuous_discharge_a"] >= 80
    assert power["controller_u2_scope"] == "JETSON_LOGIC_AND_LOW_POWER_AUXILIARIES_ONLY"
    assert set(power["controller_u2_prohibited_loads"]) == {
        "seven_axis_arms",
        "full_system_drive",
        "four_column_lift",
    }
    modes = power["operating_modes"]
    assert set(modes) == {"ARM_OPERATION", "TRANSPORT", "LIFT"}
    assert all(len(mode["allowed_high_power_loads"]) == 1 for mode in modes.values())
    assert power["battery_bus"]["selected_pack_mpn"] is None
    assert power["release_blockers"]

    with (root / "release/prephysical-component-decisions.csv").open(newline="", encoding="utf-8") as handle:
        decisions = list(csv.DictReader(handle))
    assert len(decisions) >= 16
    assert len({row["decision_id"] for row in decisions}) == len(decisions)
    assert all(
        row["preferred_candidate"].strip()
        and row["controlled_requirement"].strip()
        and row["source_or_evidence"].strip()
        and row["required_closure"].strip()
        for row in decisions
    )
    assert not any(row["decision_status"] == "APPROVED" for row in decisions)
