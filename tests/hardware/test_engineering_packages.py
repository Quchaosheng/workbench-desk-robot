from __future__ import annotations

import csv
import importlib.util
import json
import re
import tempfile
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

    def test_assembly_parts_drawings_and_drop_screen_are_present(self) -> None:
        generated = ROOT / "hardware/mechanical/generated"
        self.assertGreater((generated / "desk_robot_assembly.step").stat().st_size, 100_000)
        self.assertGreater((generated / "desk_robot_exploded.step").stat().st_size, 100_000)
        self.assertEqual(len(list((generated / "parts").glob("*.step"))), 8)
        self.assertTrue((generated / "drawings/general-arrangement.svg").exists())
        screening = json.loads((generated / "drop-screening.json").read_text(encoding="utf-8"))
        self.assertEqual(screening["acceptance"]["peak_deceleration_g"], 35)

    def test_controller_board_fits_tray_and_mount_pattern_is_controlled(self) -> None:
        module = load_module("mechanical_generator_fit", ROOT / "hardware/mechanical/tools/generate_artifacts.py")
        report = module.analyse()
        self.assertTrue(report["checks"]["pcb_fits_electronics_tray"])
        self.assertTrue(report["checks"]["pcb_edge_service_margin_met"])
        self.assertEqual(report["pcb_tray_margin_mm"], [60, 40])
        self.assertEqual(report["pcb_edge_service_margin_mm"], [30, 20])
        spec = json.loads((ROOT / "hardware/mechanical/design-spec.json").read_text(encoding="utf-8"))
        self.assertEqual(spec["electronics_tray"]["pcb_mount_pattern"], [152, 122])


class PcbPackageTests(unittest.TestCase):
    def test_power_budget_and_protection_checks_pass(self) -> None:
        module = load_module("electrical_checks", ROOT / "hardware/pcb/tools/electrical_checks.py")
        report = module.calculate()
        self.assertTrue(report["pass"])
        self.assertLess(report["input_current_at_36v_a"], 10)
        self.assertIn("LAB_VALIDATION_REQUIRED", report["status"])
        self.assertEqual(set(report["load_cases"]), {"JETSON_15W", "JETSON_25W", "JETSON_40W_MAXN"})
        self.assertEqual(set(report["input_corner_currents_a"]), {"36V", "48V", "60V"})
        self.assertTrue(report["checks"]["eight_layer_build_matches_board_thickness"])
        self.assertTrue(report["checks"]["supplier_stackup_and_impedance_closure_is_required"])
        self.assertEqual(report["nominal_stackup_thickness_mm"], 1.6)
        can = json.loads((ROOT / "hardware/pcb/electrical-spec.json").read_text(encoding="utf-8"))["can"]
        self.assertEqual(can["u7_board_pad_edge_clearance_mm"], 5.87)
        self.assertTrue(can["u7_all_copper_keepout_required"])
        self.assertTrue(can["u7_candidate_safety_suitability_open"])

    def test_eight_layer_stackup_matches_controlled_spec(self) -> None:
        spec = json.loads((ROOT / "hardware/pcb/electrical-spec.json").read_text(encoding="utf-8"))
        with (ROOT / "hardware/pcb/fabrication/stackup.csv").open(newline="", encoding="utf-8") as handle:
            stackup = list(csv.DictReader(handle))
        expected_layers = ["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "In5.Cu", "In6.Cu", "B.Cu"]
        self.assertEqual([row["layer"] for row in stackup], expected_layers)
        self.assertEqual([row["kicad_layer"] for row in spec["stackup"]], expected_layers)
        self.assertEqual(
            [(float(row["copper_oz"]), float(row["dielectric_to_next_mm"])) for row in stackup],
            [(float(row["copper_oz"]), float(row["dielectric_to_next_mm"])) for row in spec["stackup"]],
        )
        dfm = spec["dfm"]
        nominal_mm = sum(
            float(row["dielectric_to_next_mm"]) + float(row["copper_oz"]) * dfm["nominal_copper_thickness_per_oz_mm"]
            for row in stackup
        )
        self.assertAlmostEqual(nominal_mm, dfm["board_thickness_mm"], places=3)
        self.assertEqual(dfm["board_thickness_tolerance_mm"], 0.16)
        self.assertEqual(dfm["board_thickness_basis"], "finished_laminate_and_copper_excluding_solder_mask")
        self.assertEqual(dfm["surface_finish"], "ENIG")
        self.assertTrue(dfm["supplier_stackup_and_impedance_closure_required"])

    def test_every_external_connector_is_keyed_or_test_only(self) -> None:
        with (ROOT / "hardware/pcb/connectors.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertGreaterEqual(len(rows), 10)
        self.assertTrue(all(row["keying"] in {"mandatory", "polarized", "red keyed", "n/a"} for row in rows))

    def test_board_declares_eight_copper_layers_and_real_footprints(self) -> None:
        board = (ROOT / "hardware/pcb/kicad/controller.kicad_pcb").read_text(encoding="utf-8")
        copper_layers = re.findall(r'^\s*\(\d+ "(?:F|B|In\d+)\.Cu" signal\)$', board, flags=re.MULTILINE)
        self.assertEqual(len(copper_layers), 8)
        self.assertEqual(
            [layer.split('"')[1] for layer in copper_layers],
            ["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "In5.Cu", "In6.Cu", "B.Cu"],
        )
        self.assertEqual(board.count("(footprint "), 114)
        self.assertGreaterEqual(board.count("(segment"), 1_000)
        self.assertGreaterEqual(board.count("(via"), 150)
        self.assertGreaterEqual(board.count("(zone"), 18)
        for signal in [
            "SPI_SCLK",
            "MOTOR_ENABLE_REQ",
            "MOTOR_ENABLE_SAFE",
            "MOTOR_CS5",
            "I2C_SDA",
            "ESTOP_SENSE",
            "MCU_RESET",
        ]:
            self.assertIn(signal, board)
        for isolated_net in ["5V_CAN_ISO", "GND_CAN_ISO", "CAN_TX", "CAN_RX"]:
            self.assertIn(isolated_net, board)
        self.assertIn('property "Reference" "J4"', board)
        self.assertIn('property "Reference" "U7"', board)
        self.assertIn('property "Reference" "U8"', board)
        self.assertIn('property "Reference" "J11"', board)
        self.assertIn('gr_text "U2 LAND PATTERN TBD"', board)
        self.assertIn('gr_text "DO NOT FIT"', board)
        self.assertIn('(title "Workbench-1 Controller")', board)
        self.assertIn('(rev "EVT1")', board)

    def test_testpoints_are_separated_by_electrical_domain(self) -> None:
        generator = (ROOT / "hardware/pcb/tools/generate_kicad_board.py").read_text(encoding="utf-8")
        positions = {
            reference: (float(x), float(y))
            for reference, x, y in re.findall(r'"(TP\d)": \(([0-9.]+), ([0-9.]+), 0\.0\)', generator)
        }
        self.assertEqual(set(positions), {f"TP{index}" for index in range(1, 9)})
        self.assertLess(positions["TP1"][0], 46.0)
        self.assertTrue(all(positions[reference][0] >= 56.0 for reference in ["TP2", "TP3", "TP4", "TP5", "TP8"]))
        self.assertTrue(all(positions[reference][0] >= 140.0 for reference in ["TP6", "TP7"]))

    def test_pinout_and_release_audit_prevent_unsafe_order_release(self) -> None:
        module = load_module("release_readiness", ROOT / "hardware/pcb/tools/release_readiness.py")
        report = module.audit()
        self.assertTrue(report["engineering_package_pass"])
        self.assertEqual(report["status"], "ORDER_RELEASE_BLOCKED")
        self.assertTrue(report["order_release_checks"]["detailed_schematic_has_symbols"])
        self.assertFalse(report["order_release_checks"]["safety_analysis_approved"])
        self.assertTrue(report["engineering_checks"]["approval_register_covers_all_pending_bom_lines"])
        self.assertTrue(report["engineering_checks"]["bom_covers_all_board_components"])
        self.assertTrue(report["engineering_checks"]["board_layout_hard_gates_pass"])
        self.assertTrue(report["engineering_checks"]["fabrication_metadata_controlled"])
        self.assertIn("u7_isolated_power_safety_suitability", report["layout_status"]["open_risks"])
        self.assertTrue(
            report["order_release_checks"]["isolated_power_excluded_part_absent_and_tbd_placeholders_consistent"]
        )
        self.assertFalse(report["order_release_checks"]["isolated_power_mpn_and_land_pattern_frozen"])
        self.assertEqual(report["isolated_power_guard"]["incompatible_occurrences"], {})
        self.assertEqual(report["isolated_power_guard"]["required_placeholder"], "TBD_36_60V_TO_12V_240W_ISOLATED")
        self.assertEqual(report["layout_status"]["status"], "LAYOUT_HARD_GATES_PASS_RISKS_OPEN")
        self.assertIn("can_differential_impedance", report["layout_status"]["open_risks"])
        self.assertEqual(report["component_counts"], {"board_footprints": 114, "bom_references": 114})
        self.assertEqual(len(report["procurement_hold_references"]), 68)
        self.assertTrue(report["engineering_checks"]["safety_truth_table_covers_channel_discrepancy"])
        with (ROOT / "hardware/pcb/connector-pinout.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len([row for row in rows if row["reference"] == "J4"]), 20)
        self.assertEqual(len([row for row in rows if row["reference"] == "J10"]), 4)
        self.assertEqual(len([row for row in rows if row["reference"] == "J11"]), 4)
        self.assertEqual(len([row for row in rows if row["reference"] == "J12"]), 4)
        self.assertEqual(len([row for row in rows if row["reference"] == "J2"]), 4)
        self.assertEqual(len([row for row in rows if row["reference"] == "J5"]), 4)
        self.assertEqual(len([row for row in rows if row["reference"] == "J6"]), 4)
        with (ROOT / "hardware/pcb/component-selection-matrix.csv").open(newline="", encoding="utf-8") as handle:
            components = list(csv.DictReader(handle))
        component_refs = {row["reference"] for row in components}
        self.assertTrue({"U1", "U2", "U3", "U4", "U5", "U6", "U7", "U8"} <= component_refs)
        self.assertTrue({"Q1 Q2", "K1 K2", "RS1"} <= component_refs)
        u2 = next(row for row in components if row["reference"] == "U2")
        self.assertEqual(u2["primary_candidate"], "TBD_36_60V_TO_12V_240W_ISOLATED")
        with (ROOT / "hardware/pcb/component-approval-register.csv").open(newline="", encoding="utf-8") as handle:
            approvals = list(csv.DictReader(handle))
        u2_approval = next(row for row in approvals if row["reference"] == "U2")
        self.assertEqual(u2_approval["candidate"], "TBD_36_60V_TO_12V_240W_ISOLATED")
        connectivity = json.loads(
            (ROOT / "hardware/pcb/generated/connectivity_report.json").read_text(encoding="utf-8")
        )
        self.assertTrue(connectivity["pass"])
        self.assertEqual(connectivity["checked_pin_count"], 458)
        board = (ROOT / "hardware/pcb/kicad/controller.kicad_pcb").read_text(encoding="utf-8")
        self.assertTrue(all(f"TP{index}" in board for index in range(1, 9)))
        self.assertIn("Isolated_48V_12V_240W_TBD", board)
        self.assertNotIn("DCM3623", board)

    def test_official_sources_and_interface_freeze_states_are_explicit(self) -> None:
        baseline = json.loads((ROOT / "hardware/pcb/source-baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(baseline["maturity"], "EVT_REVIEWABLE_NOT_PRODUCTION_RELEASED")
        self.assertGreaterEqual(len(baseline["sources"]), 6)
        self.assertTrue(all(item["url"].startswith("https://") for item in baseline["sources"]))
        required = {"confidence", "freeze_status", "owner"}
        self.assertTrue(all(required <= item.keys() for item in baseline["sources"]))
        self.assertTrue(all(required <= item.keys() for item in baseline["controlled_assumptions"]))
        exclusion = next(item for item in baseline["sources"] if item["id"] == "SRC-VICOR-DCM3623-EXCLUSION")
        self.assertEqual(exclusion["freeze_status"], "EXCLUDED_NOT_A_CANDIDATE")
        self.assertIn("16-50 V input", exclusion["claim"])
        self.assertIn("28 V output", exclusion["claim"])
        self.assertIn("not candidate evidence", exclusion["claim"])

    def test_isolated_power_guard_rejects_excluded_part_and_non_tbd_bom(self) -> None:
        module = load_module("release_readiness_u2_guard", ROOT / "hardware/pcb/tools/release_readiness.py")
        component_matrix = [{"reference": "U2", "primary_candidate": module.ISOLATED_POWER_TBD}]
        approval_register = [{"reference": "U2", "candidate": module.ISOLATED_POWER_TBD}]
        bom = [
            {
                "reference": "U2",
                "design_candidate": module.ISOLATED_POWER_TBD,
                "package_or_module": module.ISOLATED_POWER_TBD_LAND_PATTERN,
            }
        ]
        artifacts = {
            "design_data.py": (
                f"{module.ISOLATED_POWER_TBD} {module.ISOLATED_POWER_TBD_FOOTPRINT} "
                f"{module.ISOLATED_POWER_TBD_SYMBOL}"
            ),
            "fabrication/bom.csv": module.ISOLATED_POWER_TBD,
            "controller.kicad_pcb": f"{module.ISOLATED_POWER_TBD_FOOTPRINT} U2 LAND PATTERN TBD DO NOT FIT",
            "controller.kicad_sch": (
                f"{module.ISOLATED_POWER_TBD} {module.ISOLATED_POWER_TBD_FOOTPRINT} "
                f"{module.ISOLATED_POWER_TBD_SYMBOL}"
            ),
            "controller.kicad_sym": module.ISOLATED_POWER_TBD_SYMBOL,
            "controller.ses": module.ISOLATED_POWER_TBD_FOOTPRINT,
            "controller.net": f"{module.ISOLATED_POWER_TBD} {module.ISOLATED_POWER_TBD_FOOTPRINT}",
            "fabrication/positions.csv": module.ISOLATED_POWER_TBD_FOOTPRINT,
            "WB.pretty": module.ISOLATED_POWER_TBD_FOOTPRINT,
        }
        report = module.check_isolated_power_tbd_guard(component_matrix, approval_register, bom, artifacts)
        self.assertTrue(report["pass"])
        self.assertEqual(report["missing_placeholder_markers"], {})

        stale_artifacts = {**artifacts, "controller.kicad_sch": "Vicor DCM3623T50M31C2T00"}
        report = module.check_isolated_power_tbd_guard(
            component_matrix,
            approval_register,
            bom,
            stale_artifacts,
        )
        self.assertFalse(report["pass"])
        self.assertIn("DCM3623", report["incompatible_occurrences"]["controller.kicad_sch"])

        stale_bom = [{**bom[0], "package_or_module": "WB:Vicor_DCM3623"}]
        report = module.check_isolated_power_tbd_guard(
            component_matrix,
            approval_register,
            stale_bom,
            artifacts,
        )
        self.assertFalse(report["pass"])
        self.assertFalse(report["fabrication_bom_uses_tbd"])

    def test_kicad_cli_release_reports_are_clean_and_fabrication_exists(self) -> None:
        pcb = ROOT / "hardware/pcb"
        drc = (pcb / "generated/drc.rpt").read_text(encoding="utf-8")
        erc = (pcb / "generated/erc.rpt").read_text(encoding="utf-8")
        self.assertIn("Found 0 DRC violations", drc)
        self.assertIn("Found 0 unconnected pads", drc)
        self.assertIn("0  Errors 0  Warnings", erc)
        gerbers = list((pcb / "fabrication/gerbers").glob("controller-*"))
        self.assertGreaterEqual(len(gerbers), 15)
        self.assertTrue((pcb / "fabrication/gerbers/controller-F_Paste.gtp").exists())
        self.assertTrue((pcb / "fabrication/gerbers/controller-B_Paste.gbp").exists())
        self.assertTrue((pcb / "fabrication/controller.d356").exists())
        self.assertTrue((pcb / "fabrication/drawings/assembly.pdf").exists())
        self.assertTrue((pcb / "fabrication/drawings/routing-review.pdf").exists())
        self.assertTrue((pcb / "fabrication/drawings/controller-schematic.pdf").exists())
        board_stats = json.loads((pcb / "fabrication/board-stats.json").read_text(encoding="utf-8"))
        self.assertEqual(board_stats["vias"]["total"], 180)
        self.assertEqual(
            board_stats["design_counts"]["copper_layers"],
            ["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "In5.Cu", "In6.Cu", "B.Cu"],
        )
        self.assertNotIn("", board_stats["vias"])
        self.assertIn("FAB-003", (pcb / "fabrication/fabrication-notes.csv").read_text(encoding="utf-8"))

    def test_board_stats_normalizer_replaces_locale_dependent_via_keys(self) -> None:
        module = load_module("export_fabrication_stats", ROOT / "hardware/pcb/tools/export_fabrication.py")
        with tempfile.TemporaryDirectory() as directory:
            stats_path = Path(directory) / "stats.json"
            stats_path.write_text(json.dumps({"vias": {"": 9}, "pads": {"焊盘": 1}}), encoding="utf-8")
            module.normalize_board_stats(stats_path, ROOT / "hardware/pcb/kicad/controller.kicad_pcb")
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
        self.assertEqual(stats["vias"], {"total": 180})
        self.assertEqual(stats["kicad_raw_via_summary"], {"unlabeled": 9})
        self.assertEqual(stats["design_counts"]["track_segments"], 1070)

    def test_project_enforces_documented_dfm_minimums(self) -> None:
        project = json.loads((ROOT / "hardware/pcb/kicad/controller.kicad_pro").read_text(encoding="utf-8"))
        rules = project["board"]["design_settings"]["rules"]
        self.assertEqual(rules["min_clearance"], 0.15)
        self.assertEqual(rules["min_track_width"], 0.15)
        self.assertEqual(rules["min_through_hole_diameter"], 0.3)
        self.assertEqual(rules["min_via_annular_width"], 0.15)
        custom_rules = (ROOT / "hardware/pcb/kicad/controller.kicad_dru").read_text(encoding="utf-8")
        self.assertIn("constraint clearance (min 8mm)", custom_rules)
        self.assertIn("VBAT_PROTECTED", custom_rules)
        self.assertIn("GND_PWR", custom_rules)


class ManufacturingPackageTests(unittest.TestCase):
    def test_route_is_ordered_timed_and_gated(self) -> None:
        module = load_module("route_checks", ROOT / "hardware/manufacturing/tools/validate_route.py")
        report = module.validate()
        self.assertTrue(report["pass"])
        self.assertEqual(report["operation_count"], 14)

    def test_harness_spec_has_calculated_drop_and_release_holds(self) -> None:
        module = load_module("harness_checks", ROOT / "hardware/manufacturing/tools/validate_harnesses.py")
        report = module.validate()
        self.assertTrue(report["engineering_package_pass"])
        self.assertEqual(report["status"], "HARNESS_RELEASE_BLOCKED")
        self.assertEqual(len(report["results"]), 8)
        self.assertTrue(all(item["drop_pass"] for item in report["results"]))

    def test_pilot_template_does_not_claim_units_were_built(self) -> None:
        pilot = (ROOT / "hardware/manufacturing/pilot-and-release.md").read_text(encoding="utf-8")
        self.assertIn("NOT BUILT", pilot)
        self.assertIn("NO-GO", pilot)

    def test_generated_pilot_has_twenty_serials_and_controlled_drawings(self) -> None:
        generated = ROOT / "hardware/manufacturing/generated"
        with (generated / "pilot-log.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 20)
        self.assertTrue(all(row["final_result"] == "NOT_BUILT" for row in rows))
        self.assertTrue((generated / "line-layout.svg").exists())
        self.assertTrue((generated / "fixture-drawings.svg").exists())
        self.assertTrue((generated / "packaging-drawing.svg").exists())


class ProcurementPackageTests(unittest.TestCase):
    def test_procurement_package_is_complete_without_fake_quotes(self) -> None:
        module = load_module("procurement_checks", ROOT / "hardware/procurement/tools/validate_procurement.py")
        report = module.validate()
        self.assertTrue(report["pass"])
        self.assertEqual(report["status"], "ORDER_RELEASE_BLOCKED")
        self.assertGreaterEqual(report["quote_request_count"], 2 * 4)
        self.assertTrue(all(row["unit_cost_usd"] == "" for row in module.read_csv("bom.csv")))


class QualityPackageTests(unittest.TestCase):
    def test_quality_package_has_fmea_and_explicit_execution_gates(self) -> None:
        module = load_module("qa_checks", ROOT / "hardware/qa/tools/validate_qa.py")
        report = module.validate()
        self.assertTrue(report["pass"])
        self.assertEqual(report["status"], "EXECUTION_REQUIRED")
        self.assertEqual(report["physical_results"], "NOT_EXECUTED")


class ValidationPackageTests(unittest.TestCase):
    def test_validation_package_has_fault_library_and_no_fake_units(self) -> None:
        module = load_module("validation_checks", ROOT / "hardware/validation/tools/validate_validation.py")
        report = module.validate()
        self.assertTrue(report["pass"])
        self.assertEqual(report["fault_scenario_count"], 20)
        self.assertEqual(report["first_batch_unit_count"], 10)
        self.assertEqual(report["physical_results"], "NOT_EXECUTED")

    def test_evidence_registration_fails_closed_and_accepts_valid_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw = root / "scope.csv"
            raw.write_text("time,current\n0,0\n", encoding="utf-8")
            module = load_module("validation_evidence", ROOT / "hardware/validation/tools/evidence.py")
            base = {
                "evidence_id": "EVIDENCE-001",
                "scenario_id": "VAL5-01",
                "unit_id": "UNIT-001",
                "hardware_revision": "EVT1",
                "config_hash": "a" * 64,
                "operator": "operator",
                "reviewer": "reviewer",
                "captured_at": "2026-08-18T08:00:00Z",
                "evidence_kind": "physical",
                "instrument_refs": ["SCOPE-01"],
                "calibration_refs": ["CAL-01"],
                "raw_files": {"scope.csv": module.sha256(raw)},
                "result": "PASS",
            }
            register = root / "register.jsonl"
            kwargs = {
                "root": root,
                "scenarios": {"VAL5-01"},
                "units": {"UNIT-001": ("EVT1", "a" * 64)},
            }
            module.register(register, base, **kwargs)
            self.assertEqual(module.validate_register(register, **kwargs), [base])
            with self.assertRaisesRegex(module.EvidenceError, "duplicate"):
                module.register(register, base, **kwargs)
            with self.assertRaisesRegex(module.EvidenceError, "revision mismatch"):
                module.validate_record({**base, "hardware_revision": "EVT2"}, **kwargs)
            raw.unlink()
            with self.assertRaisesRegex(module.EvidenceError, "missing"):
                module.validate_register(register, **kwargs)

    def test_physical_result_requires_physical_pass_for_every_scenario(self) -> None:
        module = load_module("validation_result_derivation", ROOT / "hardware/validation/tools/validate_validation.py")
        scenarios = {"VAL5-01", "VAL5-02"}
        simulation = [{"scenario_id": scenario, "result": "PASS"} for scenario in scenarios]
        self.assertEqual(set(module.derive_results(scenarios, simulation).values()), {"PASS"})
        physical = [{"scenario_id": "VAL5-01", "result": "PASS"}]
        self.assertEqual(module.derive_results(scenarios, physical)["VAL5-02"], "NOT_EXECUTED")


class ReleaseReadinessTests(unittest.TestCase):
    def test_release_register_is_fail_closed_and_cross_package(self) -> None:
        module = load_module("release_readiness_checks", ROOT / "hardware/release/tools/check_release_readiness.py")
        report = module.validate()
        self.assertTrue(report["pass"])
        self.assertEqual(report["status"], "RELEASE_BLOCKED")
        self.assertGreaterEqual(report["blocker_count"], 10)
        self.assertIn("REL-003A", report["blockers"])
        self.assertIn("REL-004", report["blockers"])
        self.assertIn("REL-014", report["blockers"])


class TaskPacketTests(unittest.TestCase):
    def test_task_packet_limits_writes_to_hardware_and_tests(self) -> None:
        packet = json.loads(
            (ROOT / "docs/task_packets/hardware-engineering-019-021-023.json").read_text(encoding="utf-8")
        )
        self.assertEqual(packet["issue"], "19,21,23")
        self.assertEqual(packet["issues"], [19, 21, 23])
        self.assertIn("robot/control/**", packet["forbidden"])
        self.assertIn("firmware/**", packet["forbidden"])

    def test_procurement_quality_validation_packet_is_bounded(self) -> None:
        packet = json.loads(
            (ROOT / "docs/task_packets/hardware-engineering-022-024-028.json").read_text(encoding="utf-8")
        )
        self.assertEqual(packet["issues"], [22, 24, 28])
        self.assertIn("hardware/procurement/**", packet["allowed_paths"])
        self.assertIn("hardware/qa/**", packet["allowed_paths"])
        self.assertIn("hardware/validation/**", packet["allowed_paths"])
        self.assertIn("firmware/**", packet["forbidden"])

    def test_release_readiness_packet_is_bounded(self) -> None:
        packet = json.loads(
            (ROOT / "docs/task_packets/hardware-engineering-release-readiness.json").read_text(encoding="utf-8")
        )
        self.assertEqual(packet["issues"], [19, 22, 23, 24, 28])
        self.assertIn("hardware/release/**", packet["allowed_paths"])
        self.assertIn("interfaces/**", packet["forbidden"])


if __name__ == "__main__":
    unittest.main()
