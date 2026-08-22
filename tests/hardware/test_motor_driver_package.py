from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "hardware" / "motor_driver"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def read_csv(name: str) -> list[dict[str, str]]:
    with (PACKAGE / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_motor_driver_package_is_consistent_but_order_blocked() -> None:
    validator = load_module("motor_driver_validator", PACKAGE / "tools/validate_motor_driver.py")
    report = validator.validate()
    assert report["engineering_package_pass"]
    assert report["status"] == "ORDER_RELEASE_BLOCKED"
    assert not report["order_release_ready"]
    assert all(report["checks"].values())
    assert report["metrics"]["traction_axes"] == 2
    assert report["metrics"]["j2_power_ceiling_w"] == 120
    assert report["metrics"]["j2_current_ceiling_a"] == 10
    assert report["metrics"]["controlled_driver_pin_count"] == 44
    assert report["metrics"]["candidate_motor_count"] == 1
    assert report["metrics"]["candidate_dual_stall_current_a"] == 11
    assert report["metrics"]["motor_output_path_count"] == 4
    assert report["metrics"]["independent_current_sense_path_count"] == 4
    assert report["metrics"]["encoder_interface_path_count"] == 8
    assert report["metrics"]["board_envelope_mm"] == [118.0, 82.0, 20.0]
    assert report["metrics"]["mounting_pattern_mm"] == [108.0, 72.0]
    assert set(report["release_blockers"]) >= {
        "MTR-MOTOR",
        "MTR-POWER",
        "MTR-DRV",
        "MTR-REGEN",
        "MTR-SAFETY",
        "MTR-SCHEMATIC",
        "MTR-LAYOUT",
        "MTR-THERMAL",
        "MTR-BRINGUP",
    }


def test_motor_and_regeneration_unknowns_remain_fail_closed() -> None:
    spec = json.loads((PACKAGE / "electrical-spec.json").read_text(encoding="utf-8"))
    assert spec["integration_decision"]["traction_power_stage_location"] == "INDEPENDENT_REPLACEABLE_CHILDBOARD"
    assert not spec["integration_decision"]["power_stage_on_controller_pcb"]
    assert spec["integration_decision"]["motors_are_external_chassis_assemblies"]
    assert spec["power"]["production_architecture"] is None
    assert spec["scope"]["motor_mpn"] is None
    assert spec["power"]["motor_stall_current_each_a"] is None
    assert not spec["power"]["source_sink_capability_confirmed"]
    assert spec["power"]["must_not_return_regeneration_to_j2"]
    assert spec["regeneration"]["status"] == "TBD_BLOCKING"
    assert all(value is None for key, value in spec["regeneration"].items() if key != "status")
    approvals = read_csv("component-approval-register.csv")
    assert all(row["decision"] == "PENDING" for row in approvals)
    assert all(not row["approved_mpn"].strip() for row in approvals)


def test_can_interface_preserves_controller_isolation_domain() -> None:
    spec = json.loads((PACKAGE / "electrical-spec.json").read_text(encoding="utf-8"))
    assert spec["control"]["can_interface_isolation_required"]
    assert spec["control"]["gnd_can_iso_must_not_connect_to_gnd_motor"]
    pins = {(row["pin"], row["signal"]) for row in read_csv("connector-pinout.csv") if row["reference"] == "J_CAN"}
    assert pins == {("1", "CANH"), ("2", "CANL"), ("3", "GND_CAN_ISO"), ("4", "NC")}
    assert "GND_MOTOR" not in {signal for _, signal in pins}


def test_pololu_4753_is_traceable_candidate_and_exceeds_dual_stall_budget() -> None:
    spec = json.loads((PACKAGE / "electrical-spec.json").read_text(encoding="utf-8"))
    candidate = spec["motor_candidates"][0]
    assert candidate["candidate_mpn"] == "4753"
    assert candidate["selection_status"] == "CANDIDATE_NOT_APPROVED"
    assert not candidate["production_selected"]
    assert spec["scope"]["motor_mpn"] is None
    assert candidate["simultaneous_two_axis_stall_current_a"] == 11
    assert candidate["simultaneous_two_axis_stall_current_a"] > spec["power"]["aggregate_input_current_limit_a"]
    assert candidate["analytical_no_load_linear_speed_mps"] == 0.524
    matrix = read_csv("motor-candidate-matrix.csv")[0]
    assert matrix["source_product"] == "https://www.pololu.com/product/4753"
    assert matrix["source_datasheet"].startswith("https://www.pololu.com/file/0J1736/")


def test_dual_channel_truth_table_rejects_software_bypass() -> None:
    validator = load_module("motor_driver_truth", PACKAGE / "tools/validate_motor_driver.py")
    rows = read_csv("safety-gate-truth-table.csv")
    assert all(validator.validate_truth_table(rows).values())
    unsafe = [
        *rows,
        {
            "safe_a_closed": "0",
            "safe_b_closed": "1",
            "manual_reset_complete": "1",
            "drive_request": "1",
            "driver_fault_free": "1",
            "nsleep_high_permitted": "1",
            "en_high_permitted": "1",
            "bridge_output_permitted": "1",
            "fault_latched": "0",
            "required_behavior": "unsafe_fixture",
        },
    ]
    result = validator.validate_truth_table(unsafe)
    assert not result["bridge_requires_every_permission"]
    assert not result["channel_discrepancies_disable_and_latch"]


def test_drv8962_ddv_candidate_pin_map_is_complete_and_not_approved() -> None:
    pins = read_csv("driver-pin-connectivity.csv")
    pin_numbers = [int(pin) for row in pins for pin in row["pins"].split()]
    assert sorted(pin_numbers) == list(range(1, 45))
    assert len(pin_numbers) == len(set(pin_numbers))
    assert next(row for row in pins if row["pin_name"] == "nSLEEP")["controlled_net"] == "NSLEEP_SAFE_A"
    assert {row["controlled_net"] for row in pins if row["pin_name"] in {"EN1", "EN2", "EN3", "EN4"}} == {
        "EN1_SAFE_B",
        "EN2_SAFE_B",
        "EN3_SAFE_B",
        "EN4_SAFE_B",
    }
    bom_u1 = next(row for row in read_csv("bom.csv") if row["reference"] == "U1")
    assert bom_u1["candidate_mpn_or_class"] == "DRV8962DDVR"
    assert bom_u1["selection_status"] == "CANDIDATE_NOT_APPROVED"


def test_candidate_power_return_and_fault_paths_are_explicit_and_fail_closed() -> None:
    validator = load_module("motor_driver_topology", PACKAGE / "tools/validate_motor_driver.py")
    report = validator.validate()
    assert report["checks"]["supply_ground_topology_is_closed"]
    assert report["checks"]["safety_gate_connectivity_is_fail_closed"]
    assert report["checks"]["schematic_contract_is_explicit_but_not_orderable"]
    assert report["net_topology_checks"]["logic_motor_ground_join_is_single_point"]
    assert report["net_topology_checks"]["regulator_input_and_output_are_split"]
    assert report["net_topology_checks"]["isolated_can_regulator_input_output_are_split"]
    assert all(report["interface_topology_checks"].values())
    assert report["interface_topology_checks"]["driver_vm_uses_protected_bus"]
    assert report["interface_topology_checks"]["motor_outputs_reach_exact_connector_pins"]
    assert report["interface_topology_checks"]["current_sense_paths_are_four_independent_channels"]
    assert report["interface_topology_checks"]["encoder_power_and_returns_are_closed"]
    assert report["safety_path_checks"]["nFAULT_has_two_independent_hardware_inhibits"]
    assert report["placement_direction_checks"]["rear_connectors_face_plus_y_edge"]
    assert report["metrics"]["nFAULT_hardware_inhibit_path_count"] == 2
    topology = read_csv("net-topology.csv")
    assert {row["net_name"] for row in topology} >= {
        "VM_PROTECTED",
        "VCC_LOGIC",
        "GND_MOTOR",
        "GND_LOGIC",
        "GND_CAN_ISO",
        "MOTOR_L_A",
        "MOTOR_L_B",
        "MOTOR_R_A",
        "MOTOR_R_B",
        "ENC_L_GND",
        "ENC_R_GND",
    }


def test_topology_validator_rejects_regulator_input_output_short() -> None:
    validator = load_module("motor_driver_topology_negative", PACKAGE / "tools/validate_motor_driver.py")
    topology = read_csv("net-topology.csv")
    mutated = [dict(row) for row in topology]
    input_row = next(row for row in mutated if row["topology_id"] == "PWR-05")
    input_row["source_endpoints"] = "U6.OUT"
    assert not validator.validate_net_topology(mutated)["regulator_input_and_output_are_split"]


def test_topology_validator_rejects_can_isolation_ground_crossing() -> None:
    validator = load_module("motor_driver_isolation_negative", PACKAGE / "tools/validate_motor_driver.py")
    topology = read_csv("net-topology.csv")
    mutated = [dict(row) for row in topology]
    isolated_row = next(row for row in mutated if row["topology_id"] == "PWR-11")
    isolated_row["load_endpoints"] += ";GND_MOTOR"
    assert not validator.validate_net_topology(mutated)["isolated_can_barrier_has_no_local_ground_endpoint"]


def test_interface_validator_rejects_unprotected_vm_and_crossed_motor_output() -> None:
    validator = load_module("motor_driver_interface_negative", PACKAGE / "tools/validate_motor_driver.py")
    topology = read_csv("net-topology.csv")
    pins = read_csv("driver-pin-connectivity.csv")
    connectors = read_csv("connector-pinout.csv")
    mutated_pins = [dict(row) for row in pins]
    next(row for row in mutated_pins if row["pin_name"] == "VM")["controlled_net"] = "12V_MOTOR_AUX"
    mutated_topology = [dict(row) for row in topology]
    next(row for row in mutated_topology if row["net_name"] == "MOTOR_L_A")["load_endpoints"] = "J_MR.1"
    checks = validator.validate_interface_topology(mutated_topology, mutated_pins, connectors)
    assert not checks["driver_vm_uses_protected_bus"]
    assert not checks["motor_outputs_reach_exact_connector_pins"]


def test_interface_validator_rejects_bussed_current_sense_and_open_encoder_return() -> None:
    validator = load_module("motor_driver_signal_negative", PACKAGE / "tools/validate_motor_driver.py")
    topology = read_csv("net-topology.csv")
    pins = read_csv("driver-pin-connectivity.csv")
    connectors = read_csv("connector-pinout.csv")
    mutated = [dict(row) for row in topology]
    next(row for row in mutated if row["net_name"] == "IPROPI_L_B")["load_endpoints"] = "U2.ADC_IPROPI_L_A"
    next(row for row in mutated if row["net_name"] == "ENC_R_GND")["load_endpoints"] = ""
    checks = validator.validate_interface_topology(mutated, pins, connectors)
    assert not checks["current_sense_paths_are_four_independent_channels"]
    assert not checks["encoder_power_and_returns_are_closed"]


def test_layout_review_and_kicad_concept_are_deterministic_mechanical_evidence() -> None:
    renderer = load_module("motor_driver_layout", PACKAGE / "tools/generate_layout_review.py")
    revision = json.loads((PACKAGE / "electrical-spec.json").read_text(encoding="utf-8"))["revision"]
    checked_svg = (PACKAGE / "generated/placement-review.svg").read_text(encoding="utf-8")
    assert renderer.render_svg() == checked_svg
    assert f"DUAL-AXIS TRACTION CHILDBOARD - {revision}" in checked_svg
    assert "CONCEPT ONLY - DO NOT ORDER" in checked_svg
    board = (PACKAGE / "kicad/traction-childboard-concept.kicad_pcb").read_text(encoding="utf-8")
    assert f'(rev "{revision}")' in board
    assert "CONCEPT ONLY - NO ELECTRICAL FOOTPRINTS - DO NOT ORDER" in board
    assert board.count('(property "Reference" "H') == 4
    assert board.count("(segment") == 0
    assert board.count("(zone") == 0
    drc = (PACKAGE / "generated/concept-drc.rpt").read_text(encoding="utf-8")
    assert "Found 0 DRC violations" in drc
    assert "Found 0 unconnected pads" in drc


def test_task_packet_preserves_ownership_and_stop_conditions() -> None:
    packet = json.loads(
        (ROOT / "docs/task_packets/motor-integration-traction-childboard.json").read_text(encoding="utf-8")
    )
    assert "hardware/motor_driver/**" in packet["allowed_paths"]
    assert {"interfaces/**", "robot/control/**", "firmware/**"} <= set(packet["forbidden"])
    assert any("invented" in condition for condition in packet["stop_conditions"])
    assert any("regenerative" in condition for condition in packet["stop_conditions"])
