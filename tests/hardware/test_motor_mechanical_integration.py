from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

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
    assert "UR5e" in traction["excluded_scope"]
    assert {motor["side"] for motor in motors} == {"left", "right"}
    assert motors[0]["xyz"][0] == -motors[1]["xyz"][0]
    assert motors[0]["xyz"][1:] == motors[1]["xyz"][1:]
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
    assert traction["physical_validation"] == "NOT_EXECUTED"
    assert "PHYSICAL_VALIDATION_REQUIRED" in report["status"]
    assert traction["minimum_motor_to_childboard_clearance_mm"] >= 3
    assert traction["rear_connector_corridor_mm"] >= 20


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
    assert "six UR5e joint motors" in readme
    assert "must not be ordered" in readme
    assert "vendor controller cabinet" in integration
    assert "not measured results" in integration
    assert "battery" in integration
    assert "standoff" in integration
