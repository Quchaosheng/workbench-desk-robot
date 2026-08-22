from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "hardware/pcb/tools/layout_audit.py"


def load_module():
    spec = importlib.util.spec_from_file_location("layout_audit", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def segment(net: str, start: float, end: float, width: float, layer: str = "F.Cu") -> str:
    return f'(segment (start {start} 1) (end {end} 1) (width {width}) (layer "{layer}") (net "{net}"))'


def via(
    net: str,
    x: float,
    y: float,
    diameter: float = 0.8,
    drill: float = 0.4,
    layers: tuple[str, str] = ("F.Cu", "B.Cu"),
    via_type: str | None = None,
) -> str:
    type_suffix = f" {via_type}" if via_type else ""
    return (
        f"(via{type_suffix} (at {x} {y}) (size {diameter}) (drill {drill}) "
        f'(layers "{layers[0]}" "{layers[1]}") (net "{net}"))'
    )


def u2_footprint(
    x: float = 50.0,
    y: float = 50.0,
    angle: float = 0.0,
    pad5_x: float = 0.0,
    pad5_y: float = 5.0,
) -> str:
    return f"""(footprint "TEST:U2"
        (layer "F.Cu")
        (at {x} {y} {angle})
        (property "Reference" "U2" (at 0 0 0) (layer "F.SilkS"))
        (pad "4" thru_hole circle (at 0 0) (size 4 4) (drill 1.1) (layers "*.Cu" "*.Mask") (net "12V_ISO"))
        (pad "5" thru_hole circle (at {pad5_x} {pad5_y}) (size 4 4) (drill 1.1) (layers "*.Cu" "*.Mask") (net "GND"))
    )"""


def via_array(
    net: str,
    center_x: float,
    center_y: float,
    *,
    diameter: float = 0.8,
    drill: float = 0.4,
    shift_x: float = 0.0,
    shift_y: float = 0.0,
) -> list[str]:
    return [
        via(
            net,
            center_x + column * 1.5 + shift_x,
            center_y + row * 1.5 + shift_y,
            diameter,
            drill,
        )
        for row in (-1, 0, 1)
        for column in (-1, 0, 1)
        if row != 0 or column != 0
    ]


def default_u2_parts() -> list[str]:
    return [u2_footprint(), *via_array("12V_ISO", 50, 50), *via_array("GND", 50, 55)]


def u3_footprint(x: float = 80.0, y: float = 50.0) -> str:
    return f"""(footprint "TEST:U3"
        (layer "F.Cu")
        (at {x} {y})
        (property "Reference" "U3" (at 0 0 0) (layer "F.SilkS"))
        (pad "17" smd rect (at 2.15 -0.75) (size 0.8 0.25) (layers "F.Cu") (net "JETSON_12V"))
        (pad "18" smd rect (at 2.15 -1.25) (size 0.8 0.25) (layers "F.Cu") (net "JETSON_12V"))
        (pad "25" smd rect (at 0 0) (size 2.5 2.5) (layers "F.Cu") (net "GND"))
    )"""


def u3_thermal_vias(x: float = 80.0, y: float = 50.0) -> list[str]:
    return [
        via(
            "GND",
            x - 0.25 + column * 0.4,
            y + row * 0.4,
            0.45,
            0.15,
            ("F.Cu", "In1.Cu"),
            "micro",
        )
        for row in (-1, 0, 1)
        for column in (-1, 0, 1)
    ]


def u3_output_vias(x: float = 80.0, y: float = 50.0) -> list[str]:
    return [
        via("JETSON_12V", x + offset_x, y + offset_y)
        for offset_x, offset_y in ((1.675, -3.725), (2.675, -3.725), (1.675, -3.025), (2.675, -3.025))
    ]


def default_u3_parts() -> list[str]:
    return [u3_footprint(), *u3_thermal_vias(), *u3_output_vias()]


def u6_footprint(x: float = 70.0, y: float = 70.0, pad_row_offset: float = 4.875) -> str:
    pads = []
    for index in range(8):
        pad_y = -4.445 + index * 1.27
        pads.append(f'(pad "{index + 1}" smd rect (at {-pad_row_offset} {pad_y}) (size 1.65 0.6) (layers "F.Cu"))')
        pads.append(f'(pad "{16 - index}" smd rect (at {pad_row_offset} {pad_y}) (size 1.65 0.6) (layers "F.Cu"))')
    return f"""(footprint "TEST:U6"
        (layer "F.Cu")
        (at {x} {y})
        (property "Reference" "U6" (at 0 0 0) (layer "F.SilkS"))
        {chr(10).join(pads)}
    )"""


def u6_keepout(
    x: float = 70.0,
    y: float = 70.0,
    *,
    layers: tuple[str, ...] = ("F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "In5.Cu", "In6.Cu", "B.Cu"),
    x_shift: float = 0.0,
    block_vias: bool = True,
) -> str:
    left = x - 4.05 + x_shift
    right = x + 4.05 + x_shift
    top = y - 4.745
    bottom = y + 4.745
    layer_text = " ".join(f'"{layer}"' for layer in layers)
    via_state = "not_allowed" if block_vias else "allowed"
    return f"""(zone
        (layers {layer_text})
        (keepout
            (tracks not_allowed)
            (vias {via_state})
            (pads not_allowed)
            (copperpour not_allowed)
        )
        (polygon (pts (xy {left} {top}) (xy {right} {top}) (xy {right} {bottom}) (xy {left} {bottom})))
    )"""


def default_u6_parts() -> list[str]:
    return [u6_footprint(), u6_keepout()]


def u7_footprint(x: float = 90.0, y: float = 70.0) -> str:
    return f"""(footprint "TEST:U7"
        (layer "F.Cu")
        (at {x} {y})
        (property "Reference" "U7" (at 0 0 0) (layer "F.SilkS"))
        (pad "1" thru_hole circle (at 0 0) (size 1.75 1.75) (drill 1.075) (layers "*.Cu" "*.Mask"))
        (pad "2" thru_hole circle (at 2.54 0) (size 1.75 1.75) (drill 1.075) (layers "*.Cu" "*.Mask"))
        (pad "5" thru_hole circle (at 10.16 0) (size 1.75 1.75) (drill 1.075) (layers "*.Cu" "*.Mask"))
        (pad "7" thru_hole circle (at 15.24 0) (size 1.75 1.75) (drill 1.075) (layers "*.Cu" "*.Mask"))
    )"""


def u7_keepout(
    x: float = 90.0,
    y: float = 70.0,
    *,
    layers: tuple[str, ...] = ("F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "In5.Cu", "In6.Cu", "B.Cu"),
    x_shift: float = 0.0,
) -> str:
    left = x + 3.415 + x_shift
    right = x + 9.285 + x_shift
    top = y - 0.875
    bottom = y + 0.875
    layer_text = " ".join(f'"{layer}"' for layer in layers)
    return f"""(zone
        (layers {layer_text})
        (keepout
            (tracks not_allowed)
            (vias not_allowed)
            (pads not_allowed)
            (copperpour not_allowed)
        )
        (polygon (pts (xy {left} {top}) (xy {right} {top}) (xy {right} {bottom}) (xy {left} {bottom})))
    )"""


def default_u7_parts() -> list[str]:
    return [u7_footprint(), u7_keepout()]


def raw_can_blind_vias(
    *,
    low_diameter: float = 0.6,
    layers: tuple[str, str] = ("F.Cu", "In3.Cu"),
    via_type: str = "blind",
) -> list[str]:
    return [
        via("CANH_RAW", 60, 60, 0.6, 0.3, layers, via_type),
        via("CANH_RAW", 61, 60, 0.6, 0.3, layers, via_type),
        via("CANL_RAW", 60, 62, low_diameter, 0.3, layers, via_type),
        via("CANL_RAW", 61, 62, low_diameter, 0.3, layers, via_type),
    ]


def board_text(
    *extra: str,
    omit: set[str] | None = None,
    u2_parts: list[str] | None = None,
    u3_parts: list[str] | None = None,
    u6_parts: list[str] | None = None,
    u7_parts: list[str] | None = None,
    raw_can_via_parts: list[str] | None = None,
    include_can_reference_zone: bool = True,
) -> str:
    omitted = omit or set()
    items = [
        segment("VBAT_RAW", 1, 2, 2.0),
        segment("VBAT_FUSED", 2, 3, 2.0),
        segment("FET_COMMON", 3, 4, 2.0),
        segment("INPUT_SENSE", 4, 5, 2.0),
        segment("VBAT_PROTECTED", 5, 6, 2.0),
        segment("GND_PWR", 6, 7, 2.0, "In1.Cu"),
        segment("12V_ISO", 7, 8, 2.5),
        segment("JETSON_12V", 8, 9, 1.5),
        segment("OSC_IN", 9, 10, 0.2),
        segment("OSC_OUT", 10, 11, 0.2),
        segment("CANH", 11, 21, 0.2, "In1.Cu"),
        segment("CANL", 11, 20.5, 0.2, "In1.Cu"),
        segment("CANH_RAW", 21, 31, 0.2, "In3.Cu"),
        segment("CANL_RAW", 21, 30.5, 0.2, "In3.Cu"),
        segment("MCU_RESET", 31, 32, 0.2, "In1.Cu"),
        segment("ESTOP_SENSE", 32, 33, 0.2, "In4.Cu"),
    ]
    items = [item for item in items if not any(f'(net "{net}")' in item for net in omitted)]
    items.extend(default_u2_parts() if u2_parts is None else u2_parts)
    items.extend(default_u3_parts() if u3_parts is None else u3_parts)
    items.extend(default_u6_parts() if u6_parts is None else u6_parts)
    items.extend(default_u7_parts() if u7_parts is None else u7_parts)
    items.extend(raw_can_blind_vias() if raw_can_via_parts is None else raw_can_via_parts)
    if include_can_reference_zone:
        items.append('(zone (net "GND_CAN_ISO") (layer "In1.Cu") (polygon (pts (xy 0 0) (xy 1 0) (xy 1 1))))')
    items.extend(extra)
    return "(kicad_pcb (version 20240108) (generator pcbnew)\n\t" + "\n\t".join(items) + "\n)\n"


class LayoutAuditTests(unittest.TestCase):
    def run_audit(self, text: str):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.kicad_pcb"
            path.write_text(text, encoding="utf-8")
            return module.audit(path)

    def test_hard_gates_pass_but_unprovable_impedance_stays_open(self) -> None:
        report = self.run_audit(board_text())
        self.assertTrue(report["hard_gate_pass"])
        self.assertEqual(report["status"], "LAYOUT_HARD_GATES_PASS_RISKS_OPEN")
        self.assertTrue(report["checks"]["reference_layer_net_categories"])
        self.assertEqual(
            report["risks"]["can_differential_impedance"]["status"],
            "OPEN_SUPPLIER_FIELD_SOLVE_REQUIRED",
        )
        self.assertFalse(report["risks"]["can_differential_impedance"]["machine_verifiable"])
        for risk_name in (
            "can_branched_path_correspondence",
            "can_pair_coupling_and_stub_geometry",
            "can_reference_plane_continuity",
        ):
            self.assertEqual(report["risks"][risk_name]["status"], "OPEN_LAYOUT_REVIEW_REQUIRED")
            self.assertFalse(report["risks"][risk_name]["machine_verifiable"])

    def test_u2_source_and_return_require_complete_via_arrays(self) -> None:
        report = self.run_audit(board_text())
        self.assertTrue(report["checks"]["u2_source_return_via_arrays"])
        details = report["details"]["u2_source_return_via_arrays"]
        self.assertEqual(details["U2.4"]["matched_via_count"], 8)
        self.assertEqual(details["U2.5"]["matched_via_count"], 8)

        incomplete = [
            u2_footprint(),
            *via_array("12V_ISO", 50, 50)[:-1],
            *via_array("GND", 50, 55),
        ]
        report = self.run_audit(board_text(u2_parts=incomplete))
        self.assertFalse(report["checks"]["u2_source_return_via_arrays"])
        self.assertFalse(report["hard_gate_pass"])
        self.assertEqual(report["details"]["u2_source_return_via_arrays"]["U2.4"]["matched_via_count"], 7)

    def test_u3_requires_complete_exposed_pad_microvia_array(self) -> None:
        report = self.run_audit(board_text())
        self.assertTrue(report["checks"]["u3_exposed_pad_thermal_microvia_array"])
        details = report["details"]["u3_exposed_pad_thermal_microvia_array"]
        self.assertEqual(details["matched_via_count"], 9)
        self.assertEqual(details["layers"], ["F.Cu", "In1.Cu"])

        incomplete = [u3_footprint(), *u3_thermal_vias()[:-1], *u3_output_vias()]
        report = self.run_audit(board_text(u3_parts=incomplete))
        self.assertFalse(report["checks"]["u3_exposed_pad_thermal_microvia_array"])
        self.assertFalse(report["hard_gate_pass"])
        self.assertEqual(report["details"]["u3_exposed_pad_thermal_microvia_array"]["matched_via_count"], 8)

        wrong_type = [
            u3_footprint(),
            *u3_thermal_vias()[:-1],
            via("GND", 80.15, 50.4, 0.45, 0.15, ("F.Cu", "In1.Cu")),
            *u3_output_vias(),
        ]
        report = self.run_audit(board_text(u3_parts=wrong_type))
        self.assertFalse(report["checks"]["u3_exposed_pad_thermal_microvia_array"])

    def test_u3_output_requires_four_local_parallel_transfer_vias(self) -> None:
        report = self.run_audit(board_text())
        self.assertTrue(report["checks"]["u3_output_parallel_transfer_vias"])
        details = report["details"]["u3_output_parallel_transfer_vias"]
        self.assertEqual(details["matched_via_count"], 4)
        self.assertEqual(details["minimum_via_count"], 4)

        incomplete = [u3_footprint(), *u3_thermal_vias(), *u3_output_vias()[:-1]]
        report = self.run_audit(board_text(u3_parts=incomplete))
        self.assertFalse(report["checks"]["u3_output_parallel_transfer_vias"])
        self.assertFalse(report["hard_gate_pass"])

    def test_u3_microvia_process_remains_an_open_supplier_risk(self) -> None:
        report = self.run_audit(board_text())
        risk = report["risks"]["u3_microvia_fabrication"]
        self.assertEqual(risk["status"], "OPEN_SUPPLIER_DFM_REQUIRED")
        self.assertFalse(risk["machine_verifiable"])
        for requirement in ("copper filling", "capping", "planarization"):
            self.assertIn(requirement, risk["note"])

    def test_u6_requires_full_copper_keepout_between_pad_edges(self) -> None:
        report = self.run_audit(board_text())
        self.assertTrue(report["checks"]["u6_full_copper_isolation_keepout"])
        details = report["details"]["u6_full_copper_isolation_keepout"]
        self.assertEqual(details["pad_edge_clearance_mm"], 8.1)
        self.assertEqual(details["expected_bounds_mm"], [65.95, 65.255, 74.05, 74.745])
        self.assertEqual(details["matching_rule_area_count"], 1)

        missing_layer = [
            u6_footprint(),
            u6_keepout(layers=("F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "In5.Cu", "B.Cu")),
        ]
        report = self.run_audit(board_text(u6_parts=missing_layer))
        self.assertFalse(report["checks"]["u6_full_copper_isolation_keepout"])
        candidate = report["details"]["u6_full_copper_isolation_keepout"]["rule_area_candidates"][0]
        self.assertEqual(candidate["missing_copper_layers"], ["In6.Cu"])

        shifted = [u6_footprint(), u6_keepout(x_shift=0.1)]
        report = self.run_audit(board_text(u6_parts=shifted))
        self.assertFalse(report["checks"]["u6_full_copper_isolation_keepout"])
        self.assertFalse(
            report["details"]["u6_full_copper_isolation_keepout"]["rule_area_candidates"][0]["geometry_matches"]
        )

        vias_allowed = [u6_footprint(), u6_keepout(block_vias=False)]
        report = self.run_audit(board_text(u6_parts=vias_allowed))
        self.assertFalse(report["checks"]["u6_full_copper_isolation_keepout"])
        candidate = report["details"]["u6_full_copper_isolation_keepout"]["rule_area_candidates"][0]
        self.assertFalse(candidate["restrictions"]["vias"])

    def test_u7_preserves_available_gap_but_safety_suitability_stays_open(self) -> None:
        report = self.run_audit(board_text())
        self.assertTrue(report["checks"]["u7_full_copper_isolation_keepout"])
        details = report["details"]["u7_full_copper_isolation_keepout"]
        self.assertEqual(details["pad_edge_clearance_mm"], 5.87)
        self.assertEqual(details["expected_bounds_mm"], [93.415, 69.125, 99.285, 70.875])
        self.assertFalse(details["system_target_met"])

        risk = report["risks"]["u7_isolated_power_safety_suitability"]
        self.assertEqual(risk["status"], "OPEN_SAFETY_AND_VENDOR_REVIEW_REQUIRED")
        self.assertFalse(risk["machine_verifiable"])
        self.assertIn("200 Vrms", risk["note"])

        missing_layer = [
            u7_footprint(),
            u7_keepout(layers=("F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "In5.Cu", "B.Cu")),
        ]
        report = self.run_audit(board_text(u7_parts=missing_layer))
        self.assertFalse(report["checks"]["u7_full_copper_isolation_keepout"])
        self.assertFalse(report["hard_gate_pass"])
        candidate = next(
            item
            for item in report["details"]["u7_full_copper_isolation_keepout"]["rule_area_candidates"]
            if item["missing_copper_layers"]
        )
        self.assertEqual(candidate["missing_copper_layers"], ["In6.Cu"])

    def test_raw_can_requires_two_matching_fcu_in3_blind_vias_per_net(self) -> None:
        report = self.run_audit(board_text())
        self.assertTrue(report["checks"]["raw_can_matched_fcu_in3_blind_vias"])
        details = report["details"]["raw_can_matched_fcu_in3_blind_vias"]
        self.assertTrue(details["matched_geometry"])
        self.assertEqual(details["per_net"]["CANH_RAW"]["matching_via_count"], 2)
        self.assertEqual(details["per_net"]["CANL_RAW"]["matching_via_count"], 2)

        report = self.run_audit(board_text(raw_can_via_parts=raw_can_blind_vias()[:-1]))
        self.assertFalse(report["checks"]["raw_can_matched_fcu_in3_blind_vias"])

        wrong_type = raw_can_blind_vias(via_type="micro")
        report = self.run_audit(board_text(raw_can_via_parts=wrong_type))
        self.assertFalse(report["checks"]["raw_can_matched_fcu_in3_blind_vias"])

        wrong_layers = raw_can_blind_vias(layers=("F.Cu", "In2.Cu"))
        report = self.run_audit(board_text(raw_can_via_parts=wrong_layers))
        self.assertFalse(report["checks"]["raw_can_matched_fcu_in3_blind_vias"])

        mismatched_geometry = raw_can_blind_vias(low_diameter=0.7)
        report = self.run_audit(board_text(raw_can_via_parts=mismatched_geometry))
        self.assertFalse(report["checks"]["raw_can_matched_fcu_in3_blind_vias"])
        self.assertFalse(report["details"]["raw_can_matched_fcu_in3_blind_vias"]["matched_geometry"])

    def test_raw_can_blind_vias_remain_an_open_supplier_dfm_risk(self) -> None:
        report = self.run_audit(board_text())
        risk = report["risks"]["raw_can_blind_via_fabrication"]
        self.assertEqual(risk["status"], "OPEN_SUPPLIER_DFM_REQUIRED")
        self.assertFalse(risk["machine_verifiable"])
        for requirement in ("controlled-depth drilling", "registration", "plating reliability"):
            self.assertIn(requirement, risk["note"])

    def test_can_reference_zone_declaration_is_required_but_not_impedance_proof(self) -> None:
        report = self.run_audit(board_text())
        self.assertTrue(report["checks"]["can_in1_reference_zone_declared"])
        zone_detail = report["details"]["can_in1_reference_zone_declared"]
        self.assertEqual(zone_detail["matching_zone_count"], 1)
        self.assertIn("continuity", zone_detail["note"])

        report = self.run_audit(board_text(include_can_reference_zone=False))
        self.assertFalse(report["checks"]["can_in1_reference_zone_declared"])
        self.assertFalse(report["hard_gate_pass"])

    def test_u2_via_array_accepts_tolerance_but_rejects_wrong_geometry(self) -> None:
        within_tolerance = [
            u2_footprint(),
            *via_array("12V_ISO", 50, 50, diameter=0.78, drill=0.39, shift_x=0.06, shift_y=0.06),
            *via_array("GND", 50, 55, diameter=0.78, drill=0.39, shift_x=-0.06, shift_y=0.06),
        ]
        report = self.run_audit(board_text(u2_parts=within_tolerance))
        self.assertTrue(report["checks"]["u2_source_return_via_arrays"])

        wrong_diameter = [
            u2_footprint(),
            *via_array("12V_ISO", 50, 50, diameter=0.7),
            *via_array("GND", 50, 55),
        ]
        report = self.run_audit(board_text(u2_parts=wrong_diameter))
        self.assertFalse(report["checks"]["u2_source_return_via_arrays"])
        self.assertEqual(report["details"]["u2_source_return_via_arrays"]["U2.4"]["matched_via_count"], 0)

    def test_u2_via_array_tracks_kicad_footprint_rotation(self) -> None:
        expected_centers = {
            0: (52.0, 55.0),
            90: (55.0, 48.0),
            180: (48.0, 45.0),
            270: (45.0, 52.0),
        }
        for angle, center in expected_centers.items():
            with self.subTest(angle=angle):
                rotated = [
                    u2_footprint(angle=angle, pad5_x=2.0, pad5_y=5.0),
                    *via_array("12V_ISO", 50, 50),
                    *via_array("GND", *center),
                ]
                report = self.run_audit(board_text(u2_parts=rotated))
                self.assertTrue(report["checks"]["u2_source_return_via_arrays"])
                self.assertEqual(
                    report["details"]["u2_source_return_via_arrays"]["U2.5"]["pad_center_mm"],
                    list(center),
                )

    def test_bounded_kelvin_neckdown_passes_but_long_neckdown_fails(self) -> None:
        accepted = segment("INPUT_SENSE", 40, 41.5, 0.2)
        report = self.run_audit(board_text(accepted))
        detail = report["details"]["high_current_widths_with_bounded_neckdowns"]["INPUT_SENSE"]
        self.assertTrue(detail["pass"])
        self.assertEqual(detail["state"], "bounded_neckdown")

        excessive = segment("INPUT_SENSE", 40, 45.5, 0.2)
        report = self.run_audit(board_text(excessive))
        detail = report["details"]["high_current_widths_with_bounded_neckdowns"]["INPUT_SENSE"]
        self.assertFalse(detail["pass"])
        self.assertEqual(detail["state"], "width_fail")

    def test_high_current_branch_still_requires_nominal_width_coverage(self) -> None:
        mostly_thin = segment("INPUT_SENSE", 40, 45, 0.2)
        report = self.run_audit(board_text(mostly_thin, omit={"INPUT_SENSE"}))
        detail = report["details"]["high_current_widths_with_bounded_neckdowns"]["INPUT_SENSE"]
        self.assertFalse(detail["pass"])
        self.assertTrue(any(item["reason"] == "nominal_width_coverage_too_low" for item in detail["violations"]))

    def test_low_speed_reference_layer_routing_is_allowed_but_power_is_not(self) -> None:
        report = self.run_audit(board_text())
        self.assertTrue(report["checks"]["reference_layer_net_categories"])
        power_on_reference = segment("12V_ISO", 40, 41, 2.5, "In4.Cu")
        report = self.run_audit(board_text(power_on_reference))
        self.assertFalse(report["checks"]["reference_layer_net_categories"])
        violations = report["details"]["reference_layer_net_categories"]["violations"]
        self.assertTrue(any(item["net"] == "12V_ISO" for item in violations))

    def test_can_vias_are_reported_as_risk_and_non_candidate_layer_fails(self) -> None:
        report = self.run_audit(board_text(via("CANH", 15, 1, 0.6, 0.3)))
        self.assertFalse(report["checks"]["can_candidate_layers_and_pair_delta"])
        pair = report["details"]["can_candidate_layers_and_pair_delta"]["pairs"]["CANH/CANL"]
        self.assertFalse(pair["via_counts_matched"])
        self.assertEqual(pair["via_count_delta"], 1)
        self.assertEqual(report["risks"]["can_via_discontinuities"]["status"], "OPEN_LAYOUT_REVIEW_REQUIRED")

        balanced_vias = [via("CANH", 15, 1, 0.6, 0.3), via("CANL", 15, 2, 0.6, 0.3)]
        report = self.run_audit(board_text(*balanced_vias))
        self.assertTrue(report["checks"]["can_candidate_layers_and_pair_delta"])
        pair = report["details"]["can_candidate_layers_and_pair_delta"]["pairs"]["CANH/CANL"]
        self.assertTrue(pair["via_counts_matched"])
        self.assertEqual(pair["via_count_delta"], 0)

        bad_layer = segment("CANH", 40, 41, 0.2, "In5.Cu")
        report = self.run_audit(board_text(bad_layer))
        self.assertFalse(report["checks"]["can_candidate_layers_and_pair_delta"])

    def test_branched_can_pair_uses_topology_not_aggregate_tree_length(self) -> None:
        # Matching branches can have different aggregate totals even though aggregate
        # tree length is not a differential skew metric.
        branches = [
            segment("CANH", 11, 12, 0.2, "In1.Cu"),
            segment("CANH", 12, 13, 0.2, "In1.Cu"),
            '(segment (start 12 1) (end 12 3) (width 0.2) (layer "In1.Cu") (net "CANH"))',
            segment("CANL", 11, 12, 0.2, "In1.Cu"),
            segment("CANL", 12, 13, 0.2, "In1.Cu"),
            '(segment (start 12 1) (end 12 9) (width 0.2) (layer "In1.Cu") (net "CANL"))',
        ]
        report = self.run_audit(board_text(*branches, omit={"CANH", "CANL"}))
        pair = report["details"]["can_candidate_layers_and_pair_delta"]["pairs"]["CANH/CANL"]
        self.assertTrue(pair["pass"])
        self.assertEqual(pair["topology"], "branched_multidrop")
        self.assertFalse(pair["length_matching_applicable"])
        self.assertGreater(pair["aggregate_length_delta_mm"], pair["limit_mm"])

    def test_branched_can_pair_requires_matching_topology(self) -> None:
        positive_branches = [
            '(segment (start 21 1) (end 21 3) (width 0.2) (layer "In1.Cu") (net "CANH"))',
            '(segment (start 21 1) (end 22 1) (width 0.2) (layer "In1.Cu") (net "CANH"))',
        ]
        report = self.run_audit(board_text(*positive_branches))
        pair = report["details"]["can_candidate_layers_and_pair_delta"]["pairs"]["CANH/CANL"]
        self.assertFalse(pair["pass"])
        self.assertFalse(pair["topology_compatible"])

    def test_oscillator_layer_is_a_hard_gate_but_return_path_stays_manual(self) -> None:
        inner_route = segment("OSC_IN", 40, 41, 0.2, "In2.Cu")
        report = self.run_audit(board_text(inner_route, omit={"OSC_IN"}))
        self.assertFalse(report["checks"]["oscillator_fcu_only_no_vias"])
        self.assertEqual(
            report["risks"]["oscillator_return_path_and_load"]["status"],
            "OPEN_MANUAL_REVIEW_REQUIRED",
        )
        self.assertFalse(report["risks"]["oscillator_return_path_and_load"]["machine_verifiable"])

    def test_zone_only_high_current_net_is_explicitly_not_a_pass(self) -> None:
        zone = '(zone (net "VBAT_RAW") (layer "F.Cu") (polygon (pts (xy 0 0) (xy 1 0) (xy 1 1))))'
        report = self.run_audit(board_text(zone, omit={"VBAT_RAW"}))
        detail = report["details"]["high_current_widths_with_bounded_neckdowns"]["VBAT_RAW"]
        self.assertEqual(detail["state"], "zone_only")
        self.assertFalse(detail["pass"])


if __name__ == "__main__":
    unittest.main()
