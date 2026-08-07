from __future__ import annotations

import csv
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class MechanicalPackageTests(unittest.TestCase):
    def test_analysis_passes_and_is_explicitly_analytical(self) -> None:
        module = load_module("mechanical_generator", ROOT / "hardware/mechanical/tools/generate_artifacts.py")
        report = module.analyse()
        self.assertTrue(all(report["checks"].values()))
        self.assertGreaterEqual(report["static_tip_angle_deg"], 35)
        self.assertIn("PHYSICAL_VALIDATION_REQUIRED", report["status"])

    def test_step_exchange_file_has_header_and_solid_body(self) -> None:
        step = (ROOT / "hardware/mechanical/generated/enclosure.step").read_text(encoding="ascii")
        self.assertTrue(step.startswith("ISO-10303-21;"))
        self.assertIn("END-ISO-10303-21;", step)
        self.assertIn("MANIFOLD_SOLID_BREP", step)


class PcbPackageTests(unittest.TestCase):
    def test_power_budget_and_protection_checks_pass(self) -> None:
        module = load_module("electrical_checks", ROOT / "hardware/pcb/tools/electrical_checks.py")
        report = module.calculate()
        self.assertTrue(report["pass"])
        self.assertLess(report["input_current_at_36v_a"], 10)
        self.assertIn("LAB_VALIDATION_REQUIRED", report["status"])

    def test_every_external_connector_is_keyed_or_test_only(self) -> None:
        with (ROOT / "hardware/pcb/connectors.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertGreaterEqual(len(rows), 10)
        self.assertTrue(all(row["keying"] in {"mandatory", "polarized", "red keyed", "n/a"} for row in rows))

    def test_board_declares_six_copper_layers_and_hold_marking(self) -> None:
        board = (ROOT / "hardware/pcb/kicad/controller.kicad_pcb").read_text(encoding="utf-8")
        self.assertEqual(board.count('.Cu"'), 6)
        self.assertIn("NOT FOR FABRICATION", board)


class ManufacturingPackageTests(unittest.TestCase):
    def test_route_is_ordered_timed_and_gated(self) -> None:
        module = load_module("route_checks", ROOT / "hardware/manufacturing/tools/validate_route.py")
        report = module.validate()
        self.assertTrue(report["pass"])
        self.assertEqual(report["operation_count"], 14)

    def test_pilot_template_does_not_claim_units_were_built(self) -> None:
        pilot = (ROOT / "hardware/manufacturing/pilot-and-release.md").read_text(encoding="utf-8")
        self.assertIn("NOT BUILT", pilot)
        self.assertIn("NO-GO", pilot)


class TaskPacketTests(unittest.TestCase):
    def test_task_packet_limits_writes_to_hardware_and_tests(self) -> None:
        packet = json.loads(
            (ROOT / "docs/task_packets/hardware-engineering-019-021-023.json").read_text(encoding="utf-8")
        )
        self.assertEqual(packet["issues"], [19, 21, 23])
        self.assertIn("robot/control/**", packet["forbidden"])
        self.assertIn("firmware/**", packet["forbidden"])


if __name__ == "__main__":
    unittest.main()
