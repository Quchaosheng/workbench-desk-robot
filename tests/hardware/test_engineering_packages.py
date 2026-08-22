from __future__ import annotations

import csv
import importlib.util
import json
import multiprocessing
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _register_evidence_process(module_path, register, root, record, barrier, results) -> None:
    module = load_module("validation_evidence_process", module_path)
    barrier.wait()
    try:
        module.register(
            register,
            record,
            root=root,
            scenarios={"VAL5-01"},
            units={"UNIT-001": ("EVT1", "a" * 64)},
        )
    except module.EvidenceError as exc:
        results.put(("rejected", str(exc)))
    else:
        results.put(("accepted", ""))


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

    def test_step_exports_have_reproducible_metadata_and_assembly_styles(self) -> None:
        generated = ROOT / "hardware/mechanical/generated"
        step_paths = sorted(generated.rglob("*.step"))
        self.assertGreaterEqual(len(step_paths), 19)
        for step_path in step_paths:
            step = step_path.read_text(encoding="ascii")
            self.assertIn("'2026-08-06T00:00:00'", step)
        assembly = (generated / "desk_robot_assembly.step").read_text(encoding="ascii")
        self.assertNotIn("SURFACE_STYLE_TRANSPARENT", assembly)
        self.assertNotIn("STYLED_ITEM", assembly)

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
        self.assertEqual(report["status"], "PRODUCTION_RELEASE_BLOCKED")
        self.assertEqual(report["legacy_status"], "ORDER_RELEASE_BLOCKED")
        self.assertEqual(report["evt_prototype_order"]["status"], "EVT_PROTOTYPE_ORDER_BLOCKED")
        self.assertFalse(report["evt_prototype_order"]["checks"]["critical_test_access_design_closed"])
        self.assertFalse(report["production_release"]["checks"]["critical_test_access_physically_verified"])
        self.assertTrue(report["order_release_checks"]["detailed_schematic_has_symbols"])
        self.assertFalse(report["order_release_checks"]["safety_analysis_approved"])
        self.assertTrue(report["engineering_checks"]["approval_register_covers_all_pending_bom_lines"])
        self.assertTrue(report["engineering_checks"]["bom_covers_all_board_components"])
        self.assertTrue(report["engineering_checks"]["board_layout_hard_gates_pass"])
        self.assertTrue(report["engineering_checks"]["fabrication_metadata_controlled"])
        self.assertTrue(report["engineering_checks"]["connector_limit_semantics_consistent"])
        self.assertTrue(report["engineering_checks"]["bringup_plan_covers_input_envelope_and_faults"])
        self.assertTrue(report["engineering_checks"]["critical_test_access_plan_complete"])
        self.assertTrue(report["engineering_checks"]["component_source_ids_resolve"])
        self.assertEqual(report["connector_limit_semantics"]["j2_controlled_system_limit_a"], "10")
        self.assertIn("u7_isolated_power_safety_suitability", report["layout_status"]["open_risks"])
        self.assertTrue(
            report["order_release_checks"]["isolated_power_excluded_part_absent_and_tbd_placeholders_consistent"]
        )
        self.assertFalse(report["order_release_checks"]["isolated_power_mpn_and_land_pattern_frozen"])
        self.assertEqual(report["isolated_power_guard"]["incompatible_occurrences"], {})
        self.assertEqual(report["isolated_power_guard"]["required_placeholder"], "TBD_36_60V_TO_12V_240W_ISOLATED")
        self.assertEqual(report["layout_status"]["status"], "LAYOUT_HARD_GATES_PASS_RISKS_OPEN")
        self.assertIn("can_differential_impedance", report["layout_status"]["open_risks"])
        self.assertIn("high_current_path_semantics_and_thermal", report["layout_status"]["open_risks"])
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

    def test_pcb_release_cli_fails_closed_for_blocked_stage(self) -> None:
        script = ROOT / "hardware/pcb/tools/release_readiness.py"
        production = subprocess.run([sys.executable, str(script)], cwd=ROOT, capture_output=True, text=True)
        structure = subprocess.run(
            [sys.executable, str(script), "--stage", "structure"], cwd=ROOT, capture_output=True, text=True
        )
        self.assertNotEqual(production.returncode, 0)
        self.assertEqual(structure.returncode, 0, structure.stderr)

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
        with (ROOT / "hardware/pcb/component-selection-matrix.csv").open(newline="", encoding="utf-8") as handle:
            required_source_ids = {row["source_id"] for row in csv.DictReader(handle)}
        self.assertTrue(required_source_ids <= {item["id"] for item in baseline["sources"]})

    def test_bringup_plan_is_complete_and_fails_closed_when_a_required_case_is_removed(self) -> None:
        module = load_module("release_readiness_bringup", ROOT / "hardware/pcb/tools/release_readiness.py")
        with (ROOT / "hardware/pcb/fabrication/bringup-test-plan.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        report = module.check_bringup_plan(rows)
        self.assertTrue(report["pass"])
        self.assertEqual(
            report["input_endpoint_evidence"],
            {"36V": "RAILS_36V", "48V": "RAILS_48V", "60V": "RAILS_60V"},
        )
        self.assertIn("THERMAL_SOAK_LONG", report["declared_test_ids"])
        incomplete = [row for row in rows if row["test_id"] != "REVERSE_POLARITY"]
        report = module.check_bringup_plan(incomplete)
        self.assertFalse(report["pass"])
        self.assertEqual(report["missing_test_ids"], ["REVERSE_POLARITY"])

    def test_fixture_access_plan_is_complete_but_design_and_physical_gates_remain_closed(self) -> None:
        module = load_module("release_readiness_fixture", ROOT / "hardware/pcb/tools/release_readiness.py")
        with (ROOT / "hardware/pcb/fixture-access-plan.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        with (ROOT / "hardware/pcb/connector-pinout.csv").open(newline="", encoding="utf-8") as handle:
            pinout = list(csv.DictReader(handle))
        with (ROOT / "hardware/manufacturing/fixture-budget.csv").open(newline="", encoding="utf-8") as handle:
            fixtures = list(csv.DictReader(handle))
        report = module.check_fixture_access_plan(rows, pinout, fixtures)
        self.assertTrue(report["pass"])
        self.assertFalse(report["design_ready"])
        self.assertFalse(report["release_ready"])
        self.assertIn("5V_CAN_ISO", report["eco_required_nets"])
        invalid = [dict(row) for row in rows]
        invalid[0]["planned_access"] = "J5.3"
        report = module.check_fixture_access_plan(invalid, pinout, fixtures)
        self.assertFalse(report["pass"])
        self.assertEqual(report["invalid_rows"][0]["reason"], "connector_access_does_not_match_net")
        colliding = [dict(row) for row in rows]
        eco_index = next(index for index, row in enumerate(colliding) if row["design_state"] == "ECO_REQUIRED")
        colliding[eco_index]["planned_access"] = "ECO-TP1"
        report = module.check_fixture_access_plan(colliding, pinout, fixtures)
        self.assertFalse(report["pass"])
        self.assertEqual(report["invalid_rows"][0]["reason"], "eco_testpoint_collides_with_existing_pad")

    def test_component_source_baseline_fails_closed_on_an_unresolved_source_id(self) -> None:
        module = load_module("release_readiness_sources", ROOT / "hardware/pcb/tools/release_readiness.py")
        with (ROOT / "hardware/pcb/component-selection-matrix.csv").open(newline="", encoding="utf-8") as handle:
            components = list(csv.DictReader(handle))
        baseline = json.loads((ROOT / "hardware/pcb/source-baseline.json").read_text(encoding="utf-8"))
        report = module.check_source_baseline(components, baseline)
        self.assertTrue(report["pass"])
        missing_id = components[0]["source_id"]
        incomplete = {**baseline, "sources": [item for item in baseline["sources"] if item["id"] != missing_id]}
        report = module.check_source_baseline(components, incomplete)
        self.assertFalse(report["pass"])
        self.assertEqual(report["missing_source_ids"], [missing_id])
        malformed = {**baseline, "sources": [*baseline["sources"], "not-an-object"]}
        report = module.check_source_baseline(components, malformed)
        self.assertFalse(report["pass"])
        self.assertEqual(report["invalid_sources"], ["<non-object-source>"])

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
                f"{module.ISOLATED_POWER_TBD} {module.ISOLATED_POWER_TBD_FOOTPRINT} {module.ISOLATED_POWER_TBD_SYMBOL}"
            ),
            "fabrication/bom.csv": module.ISOLATED_POWER_TBD,
            "controller.kicad_pcb": (
                f'(footprint "{module.ISOLATED_POWER_TBD_FOOTPRINT}" '
                f'(property "Reference" "U2") (attr through_hole dnp) '
                f"{module.ISOLATED_POWER_TBD_FOOTPRINT} U2 LAND PATTERN TBD DO NOT FIT)"
            ),
            "controller.kicad_sch": (
                f'  (symbol (lib_id "controller:{module.ISOLATED_POWER_TBD_SYMBOL}") '
                f'(dnp yes) (property "Reference" "U2") '
                f"{module.ISOLATED_POWER_TBD} {module.ISOLATED_POWER_TBD_FOOTPRINT} {module.ISOLATED_POWER_TBD_SYMBOL})"
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

    def test_connector_limit_semantics_rejects_ambiguous_j2_rating(self) -> None:
        module = load_module("release_readiness_connector_limits", ROOT / "hardware/pcb/tools/release_readiness.py")
        connectors = [
            {
                "reference": "J2",
                "rating": "12V 16A",
                "controlled_system_limit_a": "16",
                "limit_basis": "contact rating only",
                "branch_protection": "",
            }
        ]
        harness_rows = [{"harness_id": "H02", "max_current_a": "16"}]
        motor_spec = {"power": {"aggregate_input_current_limit_a": 10.0}}
        report = module.check_connector_limit_semantics(
            connectors,
            harness_rows,
            motor_spec,
            "J2 120 W maximum aggregate",
            "J2 120 W aggregate",
        )
        self.assertFalse(report["pass"])
        self.assertFalse(report["checks"]["contact_rating_is_explicit"])
        self.assertFalse(report["checks"]["controlled_limit_is_10a"])

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

    def test_traction_harness_package_covers_childboard_without_approval(self) -> None:
        module = load_module("traction_harness_checks", ROOT / "hardware/manufacturing/tools/validate_harnesses.py")
        report = module.validate()
        self.assertTrue(report["traction_engineering_checks"]["traction_harness_ids_complete"])
        self.assertTrue(report["traction_engineering_checks"]["traction_interfaces_cover_childboard"])
        self.assertTrue(report["traction_engineering_checks"]["traction_safety_eco_is_explicit"])
        self.assertEqual(
            {item["harness_id"] for item in report["traction_results"]}, {f"H{index:02d}" for index in range(9, 15)}
        )
        self.assertEqual(
            {item["harness_id"] for item in report["integration_results"]},
            {"H02", *{f"H{index:02d}" for index in range(9, 15)}},
        )
        self.assertEqual(len(report["all_results"]), 14)
        self.assertTrue(report["engineering_checks"]["all_fourteen_harnesses_are_evaluated"])
        self.assertTrue(report["engineering_checks"]["traction_endpoint_contract_is_explicit"])
        self.assertTrue(report["engineering_checks"]["traction_pin_maps_match_controlled_interfaces"])
        self.assertTrue(report["engineering_checks"]["traction_active_semantics_are_explicit"])
        self.assertTrue(report["engineering_checks"]["traction_shield_and_drain_semantics_are_explicit"])
        self.assertTrue(report["cross_package_checks"]["j2_harness_row_matches_controller_ceiling"])
        self.assertTrue(all(item["drop_pass"] for item in report["traction_results"]))
        self.assertFalse(report["release_checks"]["all_mating_parts_approved"])
        self.assertTrue(report["cross_package_checks"]["candidate_dual_stall_exceeds_j2_ceiling"])
        self.assertEqual(report["power_budget"]["candidate_dual_stall_current_a"], 11.0)
        self.assertEqual(report["power_budget"]["j2_aggregate_current_ceiling_a"], 10.0)
        self.assertFalse(report["release_checks"]["candidate_dual_stall_within_j2_ceiling"])

    def test_traction_harness_contract_rejects_pin_endpoint_and_shield_drift(self) -> None:
        module = load_module(
            "traction_harness_semantics_negative", ROOT / "hardware/manufacturing/tools/validate_harnesses.py"
        )
        with (ROOT / "hardware/manufacturing/harness-spec.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(module.csv.DictReader(handle))

        rows[1]["pin_map"] = "J2.1->J_PWR.1"
        checks = module._integration_semantics_checks(rows)
        self.assertFalse(checks["traction_pin_maps_match_controlled_interfaces"])

        with (ROOT / "hardware/manufacturing/harness-spec.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(module.csv.DictReader(handle))
        h11 = next(row for row in rows if row["harness_id"] == "H11")
        h11["destination_endpoint"] = h11["source_endpoint"]
        checks = module._integration_semantics_checks(rows)
        self.assertFalse(checks["endpoint_semantics_fields_are_present"])

        with (ROOT / "hardware/manufacturing/harness-spec.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(module.csv.DictReader(handle))
        h13 = next(row for row in rows if row["harness_id"] == "H13")
        h13["shield_conductors"] = "0"
        checks = module._integration_semantics_checks(rows)
        self.assertFalse(checks["signal_and_shield_conductor_counts_reconcile"])

    def test_current_j11_is_explicitly_not_the_childboard_dual_safety_endpoint(self) -> None:
        with (ROOT / "hardware/manufacturing/harness-spec.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        current_j11 = next(row for row in rows if row["harness_id"] == "H08")
        safety_eco = next(row for row in rows if row["harness_id"] == "H09")
        self.assertEqual(current_j11["source_endpoint"], "CONTROLLER_J11_CURRENT")
        self.assertEqual(current_j11["destination_endpoint"], "UNDEFINED_SINGLE_CHANNEL_DRIVER_ENDPOINT")
        self.assertEqual(safety_eco["source_endpoint"], "CONTROLLER_J10_K1_K2_SAFETY_ECO")
        self.assertEqual(safety_eco["destination_endpoint"], "TRACTION_CHILDBOARD_J_SAFE")
        self.assertNotEqual(current_j11["destination_endpoint"], safety_eco["destination_endpoint"])

    def test_harness_bend_radius_gate_rejects_underdeclared_motor_radius(self) -> None:
        module = load_module("harness_bend_negative", ROOT / "hardware/manufacturing/tools/validate_harnesses.py")
        with (ROOT / "hardware/manufacturing/harness-spec.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(module.csv.DictReader(handle))
        motor = next(row for row in rows if row["harness_id"] == "H11")
        motor["min_bend_radius_mm"] = "8"
        self.assertFalse(module.calculate_row(motor)["bend_radius_pass"])

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
    def setUp(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        self.root = Path(tempdir.name)
        self.raw = self.root / "scope.csv"
        self.raw.write_text("time,current\n0,0\n", encoding="utf-8")
        self.module_path = ROOT / "hardware/validation/tools/evidence.py"
        self.module = load_module("validation_evidence", self.module_path)
        self.register = self.root / "register.jsonl"
        self.kwargs = {
            "root": self.root,
            "scenarios": {"VAL5-01"},
            "units": {"UNIT-001": ("EVT1", "a" * 64)},
        }

    def _record(self, evidence_id: str) -> dict:
        return {
            "evidence_id": evidence_id,
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
            "raw_files": {"scope.csv": self.module.sha256(self.raw)},
            "result": "PASS",
        }

    def test_validation_package_has_fault_library_and_no_fake_units(self) -> None:
        module = load_module("validation_checks", ROOT / "hardware/validation/tools/validate_validation.py")
        report = module.validate()
        self.assertTrue(report["pass"])
        self.assertEqual(report["fault_scenario_count"], 20)
        self.assertEqual(report["first_batch_unit_count"], 10)
        self.assertEqual(report["physical_results"], "NOT_EXECUTED")

    def test_evidence_registration_fails_closed_and_accepts_valid_records(self) -> None:
        base = self._record("EVIDENCE-001")
        self.module.register(self.register, base, **self.kwargs)
        self.assertEqual(self.module.validate_register(self.register, **self.kwargs), [base])
        with self.assertRaisesRegex(self.module.EvidenceError, "duplicate"):
            self.module.register(self.register, base, **self.kwargs)
        with self.assertRaisesRegex(self.module.EvidenceError, "revision mismatch"):
            self.module.validate_record({**base, "hardware_revision": "EVT2"}, **self.kwargs)
        self.raw.unlink()
        with self.assertRaisesRegex(self.module.EvidenceError, "missing"):
            self.module.validate_register(self.register, **self.kwargs)

    def test_concurrent_duplicate_evidence_id_has_one_process_winner(self) -> None:
        record = self._record("EVIDENCE-DUPLICATE")
        context = multiprocessing.get_context("fork")
        barrier = context.Barrier(2)
        results = context.Queue()
        processes = [
            context.Process(
                target=_register_evidence_process,
                args=(self.module_path, self.register, self.root, record, barrier, results),
            )
            for _ in range(2)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join()
            self.assertEqual(process.exitcode, 0)
        outcomes = [results.get(timeout=2) for _ in processes]
        self.assertEqual(sorted(status for status, _ in outcomes), ["accepted", "rejected"])
        self.assertIn("duplicate evidence_id", next(message for status, message in outcomes if status == "rejected"))
        self.assertEqual(self.module.validate_register(self.register, **self.kwargs), [record])

    def test_concurrent_distinct_evidence_ids_are_both_retained(self) -> None:
        barrier = threading.Barrier(2)

        def register_record(record: dict) -> None:
            barrier.wait()
            self.module.register(self.register, record, **self.kwargs)

        records = [self._record(f"EVIDENCE-{index}") for index in range(2)]
        with ThreadPoolExecutor(max_workers=2) as executor:
            for future in [executor.submit(register_record, record) for record in records]:
                future.result(timeout=10)
        actual = self.module.validate_register(self.register, **self.kwargs)
        self.assertEqual({record["evidence_id"] for record in actual}, {"EVIDENCE-0", "EVIDENCE-1"})

    def test_failed_append_restores_the_valid_register(self) -> None:
        first = self._record("EVIDENCE-001")
        self.module.register(self.register, first, **self.kwargs)
        original = self.register.read_bytes()
        write = self.module.os.write

        def short_write(descriptor: int, payload: bytes) -> int:
            return write(descriptor, payload[: len(payload) // 2])

        with mock.patch.object(self.module.os, "write", side_effect=short_write):
            with self.assertRaisesRegex(OSError, "short write"):
                self.module.register(self.register, self._record("EVIDENCE-002"), **self.kwargs)
        self.assertEqual(self.register.read_bytes(), original)
        self.assertEqual(self.module.validate_register(self.register, **self.kwargs), [first])

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
        self.assertEqual(report["status"], "PRODUCTION_RELEASE_BLOCKED")
        self.assertEqual(report["legacy_status"], "RELEASE_BLOCKED")
        self.assertEqual(report["production_release"]["status"], "PRODUCTION_RELEASE_BLOCKED")
        self.assertEqual(report["evt_prototype_order"]["status"], "EVT_PROTOTYPE_ORDER_BLOCKED")
        self.assertGreaterEqual(report["blocker_count"], 10)
        self.assertIn("REL-003A", report["blockers"])
        self.assertIn("REL-004", report["blockers"])
        self.assertIn("REL-014", report["blockers"])

    def test_pass_row_cannot_mask_a_blocked_upstream_stage(self) -> None:
        module = load_module("release_readiness_bindings", ROOT / "hardware/release/tools/check_release_readiness.py")
        rows = [
            {
                "gate_id": "REL-TEST",
                "status": "PASS",
                "evidence_ref": "hardware/pcb/generated/release_readiness.json",
                "evidence_binding": "PRODUCTION_READY",
            }
        ]
        report = module.validate_evidence_bindings(rows, "gate_id")
        self.assertFalse(report["pass"])
        self.assertEqual(report["mismatches"][0]["id"], "REL-TEST")
        self.assertEqual(report["mismatches"][0]["observed_ready"], "false")

        engineering_rows = [{**rows[0], "evidence_binding": "ENGINEERING_PASS"}]
        self.assertTrue(module.validate_evidence_bindings(engineering_rows, "gate_id")["pass"])
        self.assertEqual(module.binding_mismatches(rows, "gate_id", "production_release_blocker"), [])
        rows[0]["production_release_blocker"] = "yes"
        self.assertEqual(module.binding_mismatches(rows, "gate_id", "production_release_blocker"), ["REL-TEST"])

    def test_binding_contract_rejects_downgrade_and_path_escape(self) -> None:
        module = load_module(
            "release_readiness_binding_contract", ROOT / "hardware/release/tools/check_release_readiness.py"
        )
        rows = [
            {
                "gate_id": "REL-003A",
                "status": "BLOCKED",
                "evidence_ref": "hardware/motor_driver/generated/release-readiness.json",
                "evidence_binding": "ENGINEERING_PASS",
            }
        ]
        report = module.validate_evidence_bindings(rows, "gate_id", {"REL-003A": "PRODUCTION_READY"})
        self.assertFalse(report["pass"])
        self.assertEqual(report["binding_contract_mismatches"], ["REL-003A"])
        self.assertIsNone(module.resolve_repo_ref("../outside-evidence.json"))

    def test_blocked_row_cannot_hide_a_ready_upstream_report(self) -> None:
        module = load_module(
            "release_readiness_ready_binding", ROOT / "hardware/release/tools/check_release_readiness.py"
        )
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            report_path = Path(directory) / "ready.json"
            report_path.write_text(
                json.dumps(
                    {
                        "status": "PRODUCTION_RELEASE_READY",
                        "production_release": {"ready": True},
                    }
                ),
                encoding="utf-8",
            )
            reference = report_path.relative_to(ROOT).as_posix()
            rows = [
                {
                    "closure_id": "HWC-TEST",
                    "status": "BLOCKED",
                    "evidence_ref": reference,
                    "evidence_binding": "PRODUCTION_READY",
                }
            ]
            report = module.validate_evidence_bindings(rows, "closure_id")
        self.assertFalse(report["pass"])
        self.assertEqual(report["mismatches"][0]["id"], "HWC-TEST")
        self.assertEqual(report["mismatches"][0]["observed_ready"], "true")

    def test_release_cli_fails_blocked_stages_but_allows_structure_audit(self) -> None:
        script = ROOT / "hardware/release/tools/check_release_readiness.py"
        production = subprocess.run([sys.executable, str(script)], cwd=ROOT, capture_output=True, text=True)
        evt = subprocess.run([sys.executable, str(script), "--stage", "evt"], cwd=ROOT, capture_output=True, text=True)
        structure = subprocess.run(
            [sys.executable, str(script), "--stage", "structure"], cwd=ROOT, capture_output=True, text=True
        )
        self.assertNotEqual(production.returncode, 0)
        self.assertNotEqual(evt.returncode, 0)
        self.assertEqual(structure.returncode, 0, structure.stderr)


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
