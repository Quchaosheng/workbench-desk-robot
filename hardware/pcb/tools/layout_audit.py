from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOARD = ROOT / "kicad/controller.kicad_pcb"
DEFAULT_OUTPUT = ROOT / "generated/layout_report.json"

HIGH_CURRENT_WIDTHS = {
    "VBAT_RAW": 2.0,
    "VBAT_FUSED": 2.0,
    "FET_COMMON": 2.0,
    "INPUT_SENSE": 2.0,
    "VBAT_PROTECTED": 2.0,
    "GND_PWR": 2.0,
    "12V_ISO": 2.5,
    "JETSON_12V": 1.5,
}

# Fine-pitch power-controller pads and Kelvin connections need a bounded escape
# before the route reaches its nominal current-carrying width.
NECKDOWN_RULES = {
    "VBAT_FUSED": {
        "min_width_mm": 0.2,
        "max_segment_length_mm": 1.5,
        "max_total_length_mm": 4.0,
        "min_nominal_coverage_pct": 90.0,
        "allowed_use": "LTC4368 VIN monitor branch and package escapes",
    },
    "FET_COMMON": {
        "min_width_mm": 0.65,
        "max_segment_length_mm": 1.9,
        "max_total_length_mm": 9.0,
        "min_nominal_coverage_pct": 60.0,
        "allowed_use": "back-to-back MOSFET package escapes",
    },
    "INPUT_SENSE": {
        "min_width_mm": 0.2,
        "max_segment_length_mm": 5.2,
        "max_total_length_mm": 13.5,
        "min_nominal_coverage_pct": 35.0,
        "allowed_use": "Kelvin sense branch from RS1 to LTC4368 SENSE",
    },
    "VBAT_PROTECTED": {
        "min_width_mm": 0.2,
        "max_segment_length_mm": 4.0,
        "max_total_length_mm": 7.0,
        "min_nominal_coverage_pct": 90.0,
        "allowed_use": "LTC4368 VOUT monitor branch and package escapes",
    },
    "GND_PWR": {
        "min_width_mm": 0.8,
        "max_segment_length_mm": 0.9,
        "max_total_length_mm": 2.0,
        "min_nominal_coverage_pct": 95.0,
        "allowed_use": "primary controller and divider returns",
    },
    "12V_ISO": {
        "min_width_mm": 0.2,
        "max_segment_length_mm": 3.5,
        "max_total_length_mm": 14.0,
        "min_nominal_coverage_pct": 90.0,
        "allowed_use": "parallel eFuse pins, decoupling, feedback, and control branches",
    },
    "JETSON_12V": {
        "min_width_mm": 0.25,
        "max_segment_length_mm": 1.9,
        "max_total_length_mm": 4.0,
        "min_nominal_coverage_pct": 95.0,
        "allowed_use": "parallel eFuse output pins and PGOOD divider branch",
    },
}

GROUND_NETS = {"GND_PWR", "GND", "GND_CAN_ISO"}
POWER_NETS = set(HIGH_CURRENT_WIDTHS) | {"3V3_LOGIC", "5V_CAN_ISO"}
REFERENCE_LAYERS = {"In1.Cu", "In4.Cu"}
OSCILLATOR_NETS = {"OSC_IN", "OSC_OUT"}
CAN_NETS = {"CANH", "CANL", "CANH_RAW", "CANL_RAW"}
CAN_PAIRS = (("CANH", "CANL"), ("CANH_RAW", "CANL_RAW"))
CAN_IMPEDANCE_CANDIDATE_LAYERS = {"F.Cu", "In1.Cu", "In3.Cu"}
CAN_PAIR_MAX_AGGREGATE_DELTA_MM = 5.0
CAN_TESTPOINT_STUB_MAX_MM = 3.5
CAN_TESTPOINT_PAIR_STUB_DELTA_MM = 1.0
CAN_TESTPOINT_POSITION_TOLERANCE_MM = 0.01
COPPER_LAYERS = {"F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "In5.Cu", "In6.Cu", "B.Cu"}
RAW_CAN_NETS = ("CANH_RAW", "CANL_RAW")
RAW_CAN_BLIND_VIA_LAYERS = {"F.Cu", "In3.Cu"}
RAW_CAN_BLIND_VIAS_PER_NET = 2
U6_LOGIC_PAD_NUMBERS = {str(number) for number in range(1, 9)}
U6_FIELD_PAD_NUMBERS = {str(number) for number in range(9, 17)}
U6_KEEPOUT_GEOMETRY_TOLERANCE_MM = 0.01
U7_LOGIC_PAD_NUMBERS = {"1", "2"}
U7_FIELD_PAD_NUMBERS = {"5", "7"}
U2_VIA_ARRAYS = {
    "4": {"net": "12V_ISO", "description": "isolated 12 V source transfer"},
    "5": {"net": "GND", "description": "isolated 12 V return transfer"},
}
U2_VIA_ARRAY_DIMENSION = 3
U2_VIA_ARRAY_PITCH_MM = 1.5
U2_VIA_ARRAY_REQUIRED_COUNT = U2_VIA_ARRAY_DIMENSION**2 - 1
U2_VIA_DIAMETER_MM = 0.8
U2_VIA_DRILL_MM = 0.4
U2_VIA_POSITION_TOLERANCE_MM = 0.12
U2_VIA_DIMENSION_TOLERANCE_MM = 0.05
U3_THERMAL_ARRAY_DIMENSION = 3
U3_THERMAL_ARRAY_PITCH_MM = 0.4
U3_THERMAL_ARRAY_CENTER_OFFSET_MM = (-0.25, 0.0)
U3_THERMAL_VIA_DIAMETER_MM = 0.45
U3_THERMAL_VIA_DRILL_MM = 0.15
U3_THERMAL_POSITION_TOLERANCE_MM = 0.05
U3_THERMAL_DIMENSION_TOLERANCE_MM = 0.02
U3_OUTPUT_VIA_DIAMETER_MM = 0.8
U3_OUTPUT_VIA_DRILL_MM = 0.4
U3_OUTPUT_VIA_SEARCH_RADIUS_MM = 3.0
U3_OUTPUT_MINIMUM_VIA_COUNT = 4
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def blocks(text: str, token: str) -> list[str]:
    """Return balanced S-expression blocks beginning with ``token``."""
    result: list[str] = []
    cursor = 0
    while (start := text.find(token, cursor)) >= 0:
        depth = 0
        quoted = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if escaped:
                escaped = False
                continue
            if char == "\\" and quoted:
                escaped = True
                continue
            if char == '"':
                quoted = not quoted
            elif not quoted and char == "(":
                depth += 1
            elif not quoted and char == ")":
                depth -= 1
                if depth == 0:
                    result.append(text[start : index + 1])
                    cursor = index + 1
                    break
        else:
            raise ValueError(f"unterminated block beginning with {token!r}")
    return result


def _match_number(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text)
    return float(match.group(1)) if match else None


def _net(block: str) -> str | None:
    match = re.search(r'\(net(?:\s+\d+)?\s+"([^"]+)"\)', block)
    return match.group(1) if match else None


def _parse_segments(text: str) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for block in blocks(text, "(segment"):
        start_x = _match_number(rf"\(start\s+({NUMBER})\s+{NUMBER}\)", block)
        start_y = _match_number(rf"\(start\s+{NUMBER}\s+({NUMBER})\)", block)
        end_x = _match_number(rf"\(end\s+({NUMBER})\s+{NUMBER}\)", block)
        end_y = _match_number(rf"\(end\s+{NUMBER}\s+({NUMBER})\)", block)
        width = _match_number(rf"\(width\s+({NUMBER})\)", block)
        layer_match = re.search(r'\(layer\s+"([^"]+)"\)', block)
        if None in {start_x, start_y, end_x, end_y, width} or not layer_match:
            continue
        segments.append(
            {
                "net": _net(block),
                "layer": layer_match.group(1),
                "width_mm": width,
                "start": (start_x, start_y),
                "end": (end_x, end_y),
                "length_mm": math.hypot(end_x - start_x, end_y - start_y),
            }
        )
    return segments


def _parse_vias(text: str) -> list[dict[str, Any]]:
    vias: list[dict[str, Any]] = []
    for block in blocks(text, "(via"):
        type_match = re.match(r"\(via(?:\s+([^\s()]+))?", block)
        position_x = _match_number(rf"\(at\s+({NUMBER})\s+{NUMBER}\)", block)
        position_y = _match_number(rf"\(at\s+{NUMBER}\s+({NUMBER})\)", block)
        diameter = _match_number(rf"\(size\s+({NUMBER})\)", block)
        drill = _match_number(rf"\(drill\s+({NUMBER})\)", block)
        if None in {position_x, position_y, diameter, drill}:
            continue
        layers_match = re.search(r'\(layers\s+((?:"[^"]+"\s*)+)\)', block)
        layers = re.findall(r'"([^"]+)"', layers_match.group(1)) if layers_match else []
        vias.append(
            {
                "net": _net(block),
                "type": type_match.group(1) if type_match and type_match.group(1) else "through",
                "layers": layers,
                "position": (position_x, position_y),
                "diameter_mm": diameter,
                "drill_mm": drill,
            }
        )
    return vias


def _parse_footprint_pads(text: str) -> list[dict[str, Any]]:
    pads: list[dict[str, Any]] = []
    for footprint_block in blocks(text, "(footprint"):
        reference_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', footprint_block)
        if not reference_match:
            reference_match = re.search(r'\(fp_text\s+reference\s+"([^"]+)"', footprint_block)
        footprint_at = re.search(
            rf"^\s*\(at\s+({NUMBER})\s+({NUMBER})(?:\s+({NUMBER}))?",
            footprint_block,
            re.MULTILINE,
        )
        if not reference_match or not footprint_at:
            continue
        reference = reference_match.group(1)
        footprint_x = float(footprint_at.group(1))
        footprint_y = float(footprint_at.group(2))
        footprint_angle = float(footprint_at.group(3) or 0.0)
        angle_radians = math.radians(footprint_angle)
        cosine = math.cos(angle_radians)
        sine = math.sin(angle_radians)
        for pad_block in blocks(footprint_block, "(pad"):
            number_match = re.match(r'\(pad\s+(?:"([^"]+)"|([^\s()]+))', pad_block)
            pad_at = re.search(
                rf"\(at\s+({NUMBER})\s+({NUMBER})(?:\s+({NUMBER}))?",
                pad_block,
            )
            size_match = re.search(rf"\(size\s+({NUMBER})\s+({NUMBER})\)", pad_block)
            if not number_match or not pad_at or not size_match:
                continue
            local_x = float(pad_at.group(1))
            local_y = float(pad_at.group(2))
            pad_angle = float(pad_at.group(3) or 0.0)
            pad_width = float(size_match.group(1))
            pad_height = float(size_match.group(2))
            total_angle = math.radians(footprint_angle + pad_angle)
            bounding_width = abs(pad_width * math.cos(total_angle)) + abs(pad_height * math.sin(total_angle))
            bounding_height = abs(pad_width * math.sin(total_angle)) + abs(pad_height * math.cos(total_angle))
            pads.append(
                {
                    "reference": reference,
                    "number": number_match.group(1) or number_match.group(2),
                    "net": _net(pad_block),
                    "position": (
                        footprint_x + local_x * cosine + local_y * sine,
                        footprint_y - local_x * sine + local_y * cosine,
                    ),
                    "size": (pad_width, pad_height),
                    "bounding_size": (bounding_width, bounding_height),
                }
            )
    return pads


def _parse_zones(text: str) -> list[dict[str, Any]]:
    zones: list[dict[str, Any]] = []
    for block in blocks(text, "(zone"):
        layer_match = re.search(r'\(layer\s+"([^"]+)"\)', block)
        layers_match = re.search(r'\(layers\s+((?:"[^"]+"\s*)+)\)', block)
        layers = re.findall(r'"([^"]+)"', layers_match.group(1)) if layers_match else []
        if layer_match:
            layers = [layer_match.group(1)]
        keepout_blocks = blocks(block, "(keepout")
        keepout_block = keepout_blocks[0] if keepout_blocks else ""
        polygon_blocks = blocks(block, "(polygon")
        polygon_block = polygon_blocks[0] if polygon_blocks else ""
        points = [
            (float(match.group(1)), float(match.group(2)))
            for match in re.finditer(rf"\(xy\s+({NUMBER})\s+({NUMBER})\)", polygon_block)
        ]
        zones.append(
            {
                "net": _net(block),
                "layer": layer_match.group(1) if layer_match else None,
                "layers": layers,
                "is_rule_area": bool(keepout_block),
                "keepout": {
                    item: bool(re.search(rf"\({item}\s+not_allowed\)", keepout_block))
                    for item in ("tracks", "vias", "pads", "copperpour")
                },
                "points": points,
            }
        )
    return zones


def _width_check(segments: list[dict[str, Any]], zones: list[dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    by_net: dict[str, list[dict[str, Any]]] = {net: [] for net in HIGH_CURRENT_WIDTHS}
    for segment in segments:
        if segment["net"] in by_net:
            by_net[segment["net"]].append(segment)
    zone_counts = {net: sum(zone["net"] == net for zone in zones) for net in HIGH_CURRENT_WIDTHS}
    details: dict[str, Any] = {}
    passed = True
    for net, target in HIGH_CURRENT_WIDTHS.items():
        tracks = by_net[net]
        neck_rule = NECKDOWN_RULES.get(net)
        neckdowns: list[dict[str, float]] = []
        violations: list[dict[str, float | str]] = []
        nominal_length = 0.0
        for track in tracks:
            width = track["width_mm"]
            length = track["length_mm"]
            if width + 1e-9 >= target:
                nominal_length += length
            elif (
                neck_rule
                and width + 1e-9 >= neck_rule["min_width_mm"]
                and length <= neck_rule["max_segment_length_mm"] + 1e-9
            ):
                neckdowns.append({"width_mm": width, "length_mm": length})
            else:
                violations.append({"width_mm": width, "length_mm": length, "reason": "outside_neckdown_limit"})
        neckdown_length = sum(item["length_mm"] for item in neckdowns)
        if neck_rule and neckdown_length > neck_rule["max_total_length_mm"] + 1e-9:
            violations.append(
                {
                    "length_mm": neckdown_length,
                    "limit_mm": neck_rule["max_total_length_mm"],
                    "reason": "aggregate_neckdown_too_long",
                }
            )
        total_length = sum(track["length_mm"] for track in tracks)
        nominal_coverage = 100 * nominal_length / total_length if total_length else 0.0
        if neck_rule and nominal_coverage + 1e-9 < neck_rule["min_nominal_coverage_pct"]:
            violations.append(
                {
                    "coverage_pct": nominal_coverage,
                    "limit_pct": neck_rule["min_nominal_coverage_pct"],
                    "reason": "nominal_width_coverage_too_low",
                }
            )
        if not tracks:
            state = "zone_only" if zone_counts[net] else "missing"
            net_pass = False
        else:
            net_pass = not violations
            state = "width_fail" if violations else ("bounded_neckdown" if neckdowns else "ok")
        passed = passed and net_pass
        details[net] = {
            "pass": net_pass,
            "target_width_mm": target,
            "segment_count": len(tracks),
            "min_width_mm": min((track["width_mm"] for track in tracks), default=None),
            "zone_count": zone_counts[net],
            "state": state,
            "nominal_width_coverage_pct": round(nominal_coverage, 3) if total_length else None,
            "neckdown_rule": neck_rule,
            "accepted_neckdowns": neckdowns,
            "violations": violations,
        }
    return passed, details


def _net_category(net: str) -> str:
    if net in GROUND_NETS:
        return "ground"
    if net in OSCILLATOR_NETS:
        return "oscillator"
    if net in CAN_NETS:
        return "can_differential"
    if net in POWER_NETS:
        return "power_distribution"
    return "low_speed_signal"


def _reference_layer_check(segments: list[dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    usage: dict[str, dict[str, float]] = {layer: {} for layer in REFERENCE_LAYERS}
    violations: list[dict[str, Any]] = []
    for segment in segments:
        layer = segment["layer"]
        if layer not in REFERENCE_LAYERS:
            continue
        net = segment["net"] or "<UNNAMED>"
        category = _net_category(net)
        usage[layer][category] = usage[layer].get(category, 0.0) + segment["length_mm"]
        forbidden = category in {"power_distribution", "oscillator"}
        forbidden = forbidden or (category == "can_differential" and layer != "In1.Cu")
        if forbidden:
            violations.append({"net": net, "category": category, "layer": layer, "length_mm": segment["length_mm"]})
    policy = {
        "In1.Cu": ["ground", "low_speed_signal", "can_differential"],
        "In4.Cu": ["ground", "low_speed_signal"],
    }
    return not violations, {"policy": policy, "usage_length_by_category_mm": usage, "violations": violations}


def _oscillator_check(segments: list[dict[str, Any]], vias: list[dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {}
    passed = True
    for net in sorted(OSCILLATOR_NETS):
        net_segments = [segment for segment in segments if segment["net"] == net]
        net_vias = [via for via in vias if via["net"] == net]
        off_top = sorted({segment["layer"] for segment in net_segments if segment["layer"] != "F.Cu"})
        net_pass = bool(net_segments) and not off_top and not net_vias
        passed = passed and net_pass
        details[net] = {
            "pass": net_pass,
            "segment_count": len(net_segments),
            "via_count": len(net_vias),
            "layers": sorted({segment["layer"] for segment in net_segments}),
            "non_fcu_layers": off_top,
            "aggregate_length_mm": sum(segment["length_mm"] for segment in net_segments),
        }
    return passed, details


def _can_reference_zone_check(zones: list[dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    declared = any(zone["net"] == "GND_CAN_ISO" and zone["layer"] == "In1.Cu" for zone in zones)
    return declared, {
        "pass": declared,
        "required_net": "GND_CAN_ISO",
        "required_layer": "In1.Cu",
        "matching_zone_count": sum(zone["net"] == "GND_CAN_ISO" and zone["layer"] == "In1.Cu" for zone in zones),
        "note": "Declaration presence only; continuity, clearance, and impedance remain manual/supplier checks.",
    }


def _isolation_keepout_check(
    reference: str,
    logic_pad_numbers: set[str],
    field_pad_numbers: set[str],
    pads: list[dict[str, Any]],
    zones: list[dict[str, Any]],
    minimum_clearance_mm: float,
) -> tuple[bool, dict[str, Any]]:
    component_pads = {pad["number"]: pad for pad in pads if pad["reference"] == reference}
    missing_logic_pads = sorted(logic_pad_numbers - component_pads.keys(), key=int)
    missing_field_pads = sorted(field_pad_numbers - component_pads.keys(), key=int)
    if missing_logic_pads or missing_field_pads:
        return False, {
            "pass": False,
            "reason": "required_isolation_pads_missing",
            "reference": reference,
            "missing_logic_pads": missing_logic_pads,
            "missing_field_pads": missing_field_pads,
        }

    logic_pads = [component_pads[number] for number in logic_pad_numbers]
    field_pads = [component_pads[number] for number in field_pad_numbers]
    all_pads = [*logic_pads, *field_pads]
    logic_edge = max(pad["position"][0] + pad["bounding_size"][0] / 2 for pad in logic_pads)
    field_edge = min(pad["position"][0] - pad["bounding_size"][0] / 2 for pad in field_pads)
    top = min(pad["position"][1] - pad["bounding_size"][1] / 2 for pad in all_pads)
    bottom = max(pad["position"][1] + pad["bounding_size"][1] / 2 for pad in all_pads)
    expected_bounds = (logic_edge, top, field_edge, bottom)
    candidate_details: list[dict[str, Any]] = []
    matching_count = 0
    for zone in zones:
        if not zone["is_rule_area"] or not zone["points"]:
            continue
        x_values = [point[0] for point in zone["points"]]
        y_values = [point[1] for point in zone["points"]]
        actual_bounds = (min(x_values), min(y_values), max(x_values), max(y_values))
        layers_complete = COPPER_LAYERS <= set(zone["layers"])
        restrictions_complete = all(zone["keepout"][item] for item in ("tracks", "vias", "copperpour"))
        geometry_matches = all(
            abs(actual - expected) <= U6_KEEPOUT_GEOMETRY_TOLERANCE_MM
            for actual, expected in zip(actual_bounds, expected_bounds, strict=True)
        )
        candidate_pass = layers_complete and restrictions_complete and geometry_matches
        matching_count += int(candidate_pass)
        candidate_details.append(
            {
                "pass": candidate_pass,
                "bounds_mm": [round(value, 4) for value in actual_bounds],
                "layers_complete": layers_complete,
                "missing_copper_layers": sorted(COPPER_LAYERS - set(zone["layers"])),
                "restrictions": zone["keepout"],
                "geometry_matches": geometry_matches,
            }
        )
    clearance_mm = field_edge - logic_edge
    passed = clearance_mm + 1e-9 >= minimum_clearance_mm and matching_count == 1
    return passed, {
        "pass": passed,
        "reference": reference,
        "pad_edge_clearance_mm": round(clearance_mm, 4),
        "minimum_pad_edge_clearance_mm": minimum_clearance_mm,
        "expected_bounds_mm": [round(value, 4) for value in expected_bounds],
        "required_layers": sorted(COPPER_LAYERS),
        "required_restrictions": ["tracks", "vias", "copperpour"],
        "matching_rule_area_count": matching_count,
        "rule_area_candidates": candidate_details,
    }


def _u6_isolation_keepout_check(pads: list[dict[str, Any]], zones: list[dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    return _isolation_keepout_check("U6", U6_LOGIC_PAD_NUMBERS, U6_FIELD_PAD_NUMBERS, pads, zones, 8.0)


def _u7_isolation_keepout_check(pads: list[dict[str, Any]], zones: list[dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    passed, details = _isolation_keepout_check("U7", U7_LOGIC_PAD_NUMBERS, U7_FIELD_PAD_NUMBERS, pads, zones, 0.0)
    details["system_target_clearance_mm"] = 8.0
    details["system_target_met"] = details.get("pad_edge_clearance_mm", 0.0) >= 8.0
    return passed, details


def _raw_can_blind_via_check(vias: list[dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {}
    signatures: dict[str, set[tuple[float, float]]] = {}
    passed = True
    for net_name in RAW_CAN_NETS:
        net_vias = [via for via in vias if via["net"] == net_name]
        matching = [
            via for via in net_vias if via["type"] == "blind" and set(via["layers"]) == RAW_CAN_BLIND_VIA_LAYERS
        ]
        signatures[net_name] = {(round(via["diameter_mm"], 4), round(via["drill_mm"], 4)) for via in matching}
        net_pass = len(net_vias) == RAW_CAN_BLIND_VIAS_PER_NET and len(matching) == RAW_CAN_BLIND_VIAS_PER_NET
        passed = passed and net_pass
        details[net_name] = {
            "pass": net_pass,
            "required_via_count": RAW_CAN_BLIND_VIAS_PER_NET,
            "total_via_count": len(net_vias),
            "matching_via_count": len(matching),
            "required_type": "blind",
            "required_layers": sorted(RAW_CAN_BLIND_VIA_LAYERS),
            "matched_vias": [
                {
                    "position_mm": [round(value, 4) for value in via["position"]],
                    "diameter_mm": via["diameter_mm"],
                    "drill_mm": via["drill_mm"],
                }
                for via in matching
            ],
        }
    common_signature = signatures[RAW_CAN_NETS[0]] == signatures[RAW_CAN_NETS[1]]
    common_signature = common_signature and len(signatures[RAW_CAN_NETS[0]]) == 1
    passed = passed and common_signature
    return passed, {
        "pass": passed,
        "per_net": details,
        "matched_geometry": common_signature,
        "geometry_by_net": {
            net_name: [list(signature) for signature in sorted(signatures[net_name])] for net_name in RAW_CAN_NETS
        },
    }


def _u2_via_array_check(pads: list[dict[str, Any]], vias: list[dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {}
    passed = True
    offsets = [
        (column * U2_VIA_ARRAY_PITCH_MM, row * U2_VIA_ARRAY_PITCH_MM)
        for row in range(-(U2_VIA_ARRAY_DIMENSION // 2), U2_VIA_ARRAY_DIMENSION // 2 + 1)
        for column in range(-(U2_VIA_ARRAY_DIMENSION // 2), U2_VIA_ARRAY_DIMENSION // 2 + 1)
        if row != 0 or column != 0
    ]
    for pad_number, rule in U2_VIA_ARRAYS.items():
        matching_pads = [
            pad
            for pad in pads
            if pad["reference"] == "U2" and pad["number"] == pad_number and pad["net"] == rule["net"]
        ]
        if len(matching_pads) != 1:
            passed = False
            details[f"U2.{pad_number}"] = {
                "pass": False,
                "net": rule["net"],
                "description": rule["description"],
                "reason": "required_pad_missing_or_ambiguous",
                "matching_pad_count": len(matching_pads),
            }
            continue

        pad_x, pad_y = matching_pads[0]["position"]
        expected_positions = [(pad_x + offset_x, pad_y + offset_y) for offset_x, offset_y in offsets]
        dimension_candidates = [
            via
            for via in vias
            if via["net"] == rule["net"]
            and abs(via["diameter_mm"] - U2_VIA_DIAMETER_MM) <= U2_VIA_DIMENSION_TOLERANCE_MM
            and abs(via["drill_mm"] - U2_VIA_DRILL_MM) <= U2_VIA_DIMENSION_TOLERANCE_MM
            and via["layers"][:2] == ["F.Cu", "B.Cu"]
        ]
        available = set(range(len(dimension_candidates)))
        matched_vias: list[dict[str, Any]] = []
        missing_positions: list[tuple[float, float]] = []
        for expected_x, expected_y in expected_positions:
            candidates = sorted(
                (
                    math.hypot(
                        dimension_candidates[index]["position"][0] - expected_x,
                        dimension_candidates[index]["position"][1] - expected_y,
                    ),
                    index,
                )
                for index in available
            )
            if not candidates or candidates[0][0] > U2_VIA_POSITION_TOLERANCE_MM:
                missing_positions.append((expected_x, expected_y))
                continue
            distance, index = candidates[0]
            available.remove(index)
            via = dimension_candidates[index]
            matched_vias.append(
                {
                    "position_mm": [round(value, 4) for value in via["position"]],
                    "position_error_mm": round(distance, 4),
                    "diameter_mm": via["diameter_mm"],
                    "drill_mm": via["drill_mm"],
                }
            )
        pad_pass = not missing_positions and len(matched_vias) == U2_VIA_ARRAY_REQUIRED_COUNT
        passed = passed and pad_pass
        details[f"U2.{pad_number}"] = {
            "pass": pad_pass,
            "net": rule["net"],
            "description": rule["description"],
            "pad_center_mm": [round(pad_x, 4), round(pad_y, 4)],
            "required_shape": f"{U2_VIA_ARRAY_DIMENSION}x{U2_VIA_ARRAY_DIMENSION} ring around the THT pad",
            "pitch_mm": U2_VIA_ARRAY_PITCH_MM,
            "via_diameter_mm": U2_VIA_DIAMETER_MM,
            "via_drill_mm": U2_VIA_DRILL_MM,
            "position_tolerance_mm": U2_VIA_POSITION_TOLERANCE_MM,
            "dimension_tolerance_mm": U2_VIA_DIMENSION_TOLERANCE_MM,
            "matched_via_count": len(matched_vias),
            "matched_vias": matched_vias,
            "missing_positions_mm": [[round(x, 4), round(y, 4)] for x, y in missing_positions],
        }
    return passed, details


def _u3_thermal_via_check(pads: list[dict[str, Any]], vias: list[dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    matching_pads = [pad for pad in pads if pad["reference"] == "U3" and pad["number"] == "25" and pad["net"] == "GND"]
    if len(matching_pads) != 1:
        return False, {
            "pass": False,
            "reason": "required_pad_missing_or_ambiguous",
            "matching_pad_count": len(matching_pads),
        }

    pad_x, pad_y = matching_pads[0]["position"]
    center_x = pad_x + U3_THERMAL_ARRAY_CENTER_OFFSET_MM[0]
    center_y = pad_y + U3_THERMAL_ARRAY_CENTER_OFFSET_MM[1]
    expected_positions = [
        (center_x + column * U3_THERMAL_ARRAY_PITCH_MM, center_y + row * U3_THERMAL_ARRAY_PITCH_MM)
        for row in range(-(U3_THERMAL_ARRAY_DIMENSION // 2), U3_THERMAL_ARRAY_DIMENSION // 2 + 1)
        for column in range(-(U3_THERMAL_ARRAY_DIMENSION // 2), U3_THERMAL_ARRAY_DIMENSION // 2 + 1)
    ]
    candidates = [
        via
        for via in vias
        if via["net"] == "GND"
        and via["type"] == "micro"
        and via["layers"][:2] == ["F.Cu", "In1.Cu"]
        and abs(via["diameter_mm"] - U3_THERMAL_VIA_DIAMETER_MM) <= U3_THERMAL_DIMENSION_TOLERANCE_MM
        and abs(via["drill_mm"] - U3_THERMAL_VIA_DRILL_MM) <= U3_THERMAL_DIMENSION_TOLERANCE_MM
    ]
    available = set(range(len(candidates)))
    matched_vias: list[dict[str, Any]] = []
    missing_positions: list[tuple[float, float]] = []
    for expected_x, expected_y in expected_positions:
        nearest = sorted(
            (
                math.hypot(
                    candidates[index]["position"][0] - expected_x,
                    candidates[index]["position"][1] - expected_y,
                ),
                index,
            )
            for index in available
        )
        if not nearest or nearest[0][0] > U3_THERMAL_POSITION_TOLERANCE_MM:
            missing_positions.append((expected_x, expected_y))
            continue
        distance, index = nearest[0]
        available.remove(index)
        via = candidates[index]
        matched_vias.append(
            {
                "position_mm": [round(value, 4) for value in via["position"]],
                "position_error_mm": round(distance, 4),
            }
        )
    required_count = U3_THERMAL_ARRAY_DIMENSION**2
    passed = not missing_positions and len(matched_vias) == required_count
    return passed, {
        "pass": passed,
        "pad_center_mm": [round(pad_x, 4), round(pad_y, 4)],
        "array_center_offset_mm": list(U3_THERMAL_ARRAY_CENTER_OFFSET_MM),
        "required_shape": f"{U3_THERMAL_ARRAY_DIMENSION}x{U3_THERMAL_ARRAY_DIMENSION}",
        "pitch_mm": U3_THERMAL_ARRAY_PITCH_MM,
        "via_type": "micro",
        "layers": ["F.Cu", "In1.Cu"],
        "via_diameter_mm": U3_THERMAL_VIA_DIAMETER_MM,
        "via_drill_mm": U3_THERMAL_VIA_DRILL_MM,
        "matched_via_count": len(matched_vias),
        "matched_vias": matched_vias,
        "missing_positions_mm": [[round(x, 4), round(y, 4)] for x, y in missing_positions],
    }


def _u3_output_via_check(pads: list[dict[str, Any]], vias: list[dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    output_pads = [
        pad for pad in pads if pad["reference"] == "U3" and pad["number"] in {"17", "18"} and pad["net"] == "JETSON_12V"
    ]
    if len(output_pads) != 2:
        return False, {
            "pass": False,
            "reason": "required_output_pads_missing_or_ambiguous",
            "matching_pad_count": len(output_pads),
        }

    center_x = sum(pad["position"][0] for pad in output_pads) / len(output_pads)
    center_y = sum(pad["position"][1] for pad in output_pads) / len(output_pads)
    candidates = [
        via
        for via in vias
        if via["net"] == "JETSON_12V"
        and via["type"] == "through"
        and via["layers"][:2] == ["F.Cu", "B.Cu"]
        and abs(via["diameter_mm"] - U3_OUTPUT_VIA_DIAMETER_MM) <= U2_VIA_DIMENSION_TOLERANCE_MM
        and abs(via["drill_mm"] - U3_OUTPUT_VIA_DRILL_MM) <= U2_VIA_DIMENSION_TOLERANCE_MM
        and math.hypot(via["position"][0] - center_x, via["position"][1] - center_y) <= U3_OUTPUT_VIA_SEARCH_RADIUS_MM
    ]
    passed = len(candidates) >= U3_OUTPUT_MINIMUM_VIA_COUNT
    return passed, {
        "pass": passed,
        "output_pad_midpoint_mm": [round(center_x, 4), round(center_y, 4)],
        "minimum_via_count": U3_OUTPUT_MINIMUM_VIA_COUNT,
        "search_radius_mm": U3_OUTPUT_VIA_SEARCH_RADIUS_MM,
        "via_type": "through",
        "layers": ["F.Cu", "B.Cu"],
        "via_diameter_mm": U3_OUTPUT_VIA_DIAMETER_MM,
        "via_drill_mm": U3_OUTPUT_VIA_DRILL_MM,
        "matched_via_count": len(candidates),
        "matched_vias": [{"position_mm": [round(value, 4) for value in via["position"]]} for via in candidates],
    }


def _can_testpoint_stub_check(
    pads: list[dict[str, Any]], segments: list[dict[str, Any]]
) -> tuple[bool, dict[str, Any]]:
    """Check that CAN probe pads use short, paired, same-layer branches."""
    targets = (("TP6", "CANH"), ("TP7", "CANL"))
    target_references = {reference for reference, _ in targets}
    details: dict[str, Any] = {
        "max_stub_length_mm": CAN_TESTPOINT_STUB_MAX_MM,
        "pair_stub_delta_limit_mm": CAN_TESTPOINT_PAIR_STUB_DELTA_MM,
        "position_tolerance_mm": CAN_TESTPOINT_POSITION_TOLERANCE_MM,
    }
    if not any(pad["reference"] in target_references for pad in pads):
        return True, {**details, "state": "not_applicable", "pass": True, "points": {}}

    point_lengths: dict[str, float] = {}
    all_pass = True
    points: dict[str, Any] = {}
    for reference, net in targets:
        matching_pads = [pad for pad in pads if pad["reference"] == reference and pad["net"] == net]
        if len(matching_pads) != 1:
            points[reference] = {"pass": False, "reason": "pad_missing_or_ambiguous", "count": len(matching_pads)}
            all_pass = False
            continue
        position = matching_pads[0]["position"]
        touching = [
            segment
            for segment in segments
            if segment["net"] == net
            and (
                math.hypot(segment["start"][0] - position[0], segment["start"][1] - position[1])
                <= CAN_TESTPOINT_POSITION_TOLERANCE_MM
                or math.hypot(segment["end"][0] - position[0], segment["end"][1] - position[1])
                <= CAN_TESTPOINT_POSITION_TOLERANCE_MM
            )
        ]
        if len(touching) != 1:
            points[reference] = {
                "pass": False,
                "reason": "expected_one_direct_stub_segment",
                "segment_count": len(touching),
            }
            all_pass = False
            continue
        stub = touching[0]
        point_lengths[reference] = stub["length_mm"]
        stub_pass = stub["layer"] == "F.Cu" and stub["length_mm"] <= CAN_TESTPOINT_STUB_MAX_MM
        points[reference] = {
            "pass": stub_pass,
            "net": net,
            "layer": stub["layer"],
            "stub_length_mm": round(stub["length_mm"], 4),
            "start": list(stub["start"]),
            "end": list(stub["end"]),
        }
        all_pass = all_pass and stub_pass

    if len(point_lengths) == 2:
        pair_delta = abs(point_lengths["TP6"] - point_lengths["TP7"])
        details["pair_stub_delta_mm"] = round(pair_delta, 4)
        details["pair_match_pass"] = pair_delta <= CAN_TESTPOINT_PAIR_STUB_DELTA_MM
        all_pass = all_pass and details["pair_match_pass"]
    else:
        details["pair_match_pass"] = False
    details["points"] = points
    details["state"] = "checked"
    details["pass"] = all_pass
    return all_pass, details


def _can_check(segments: list[dict[str, Any]], vias: list[dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {}
    lengths: dict[str, float] = {}
    routing_pass = True
    for net in sorted(CAN_NETS):
        net_segments = [segment for segment in segments if segment["net"] == net]
        off_policy = sorted(
            {segment["layer"] for segment in net_segments if segment["layer"] not in CAN_IMPEDANCE_CANDIDATE_LAYERS}
        )
        net_pass = bool(net_segments) and not off_policy
        routing_pass = routing_pass and net_pass
        lengths[net] = sum(segment["length_mm"] for segment in net_segments)
        details[net] = {
            "pass": net_pass,
            "segment_count": len(net_segments),
            "via_count": sum(via["net"] == net for via in vias),
            "layers": sorted({segment["layer"] for segment in net_segments}),
            "layers_outside_impedance_candidates": off_policy,
            "aggregate_length_mm": lengths[net],
        }
    pair_details: dict[str, Any] = {}
    pair_pass = True
    for positive, negative in CAN_PAIRS:
        delta = abs(lengths[positive] - lengths[negative])
        positive_segments = [segment for segment in segments if segment["net"] == positive]
        negative_segments = [segment for segment in segments if segment["net"] == negative]

        def branched(net_segments: list[dict[str, Any]]) -> bool:
            endpoint_degree: dict[tuple[float, float], int] = {}
            for segment in net_segments:
                for endpoint in (segment["start"], segment["end"]):
                    key = (round(endpoint[0], 4), round(endpoint[1], 4))
                    endpoint_degree[key] = endpoint_degree.get(key, 0) + 1
            return any(degree > 2 for degree in endpoint_degree.values())

        positive_branched = branched(positive_segments)
        negative_branched = branched(negative_segments)
        pair_is_branched = positive_branched or negative_branched
        positive_layers = {segment["layer"] for segment in positive_segments}
        negative_layers = {segment["layer"] for segment in negative_segments}
        topology_compatible = positive_branched == negative_branched
        topology_compatible = topology_compatible and positive_layers == negative_layers
        length_matched = delta <= CAN_PAIR_MAX_AGGREGATE_DELTA_MM
        positive_via_count = sum(via["net"] == positive for via in vias)
        negative_via_count = sum(via["net"] == negative for via in vias)
        via_count_delta = abs(positive_via_count - negative_via_count)
        via_counts_matched = via_count_delta == 0
        matched = bool(lengths[positive] and lengths[negative]) and topology_compatible and via_counts_matched
        if not pair_is_branched:
            matched = matched and length_matched
        pair_pass = pair_pass and matched
        pair_details[f"{positive}/{negative}"] = {
            "pass": matched,
            "topology": "branched_multidrop" if pair_is_branched else "point_to_point",
            "length_matching_applicable": not pair_is_branched,
            "topology_compatible": topology_compatible,
            "via_counts_matched": via_counts_matched,
            "via_count_delta": via_count_delta,
            "aggregate_length_delta_mm": delta,
            "limit_mm": CAN_PAIR_MAX_AGGREGATE_DELTA_MM,
        }
    return routing_pass and pair_pass, {"nets": details, "pairs": pair_details}


def audit(board_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(board_path) if board_path is not None else DEFAULT_BOARD
    text = path.read_text(encoding="utf-8")
    segments = _parse_segments(text)
    vias = _parse_vias(text)
    pads = _parse_footprint_pads(text)
    zones = _parse_zones(text)
    width_pass, width_details = _width_check(segments, zones)
    layer_pass, layer_details = _reference_layer_check(segments)
    oscillator_pass, oscillator_details = _oscillator_check(segments, vias)
    can_reference_zone_pass, can_reference_zone_details = _can_reference_zone_check(zones)
    u6_keepout_pass, u6_keepout_details = _u6_isolation_keepout_check(pads, zones)
    u7_keepout_pass, u7_keepout_details = _u7_isolation_keepout_check(pads, zones)
    u2_via_array_pass, u2_via_array_details = _u2_via_array_check(pads, vias)
    u3_thermal_via_pass, u3_thermal_via_details = _u3_thermal_via_check(pads, vias)
    u3_output_via_pass, u3_output_via_details = _u3_output_via_check(pads, vias)
    raw_can_blind_via_pass, raw_can_blind_via_details = _raw_can_blind_via_check(vias)
    can_pass, can_details = _can_check(segments, vias)
    can_testpoint_pass, can_testpoint_details = _can_testpoint_stub_check(pads, segments)
    checks = {
        "high_current_widths_with_bounded_neckdowns": width_pass,
        "reference_layer_net_categories": layer_pass,
        "oscillator_fcu_only_no_vias": oscillator_pass,
        "can_in1_reference_zone_declared": can_reference_zone_pass,
        "u6_full_copper_isolation_keepout": u6_keepout_pass,
        "u7_full_copper_isolation_keepout": u7_keepout_pass,
        "u2_source_return_via_arrays": u2_via_array_pass,
        "u3_exposed_pad_thermal_microvia_array": u3_thermal_via_pass,
        "u3_output_parallel_transfer_vias": u3_output_via_pass,
        "raw_can_matched_fcu_in3_blind_vias": raw_can_blind_via_pass,
        "can_candidate_layers_and_pair_delta": can_pass,
        "can_testpoint_stub_geometry": can_testpoint_pass,
    }
    can_vias = {net: sum(via["net"] == net for via in vias) for net in sorted(CAN_NETS)}
    risks = {
        "can_differential_impedance": {
            "status": "OPEN_SUPPLIER_FIELD_SOLVE_REQUIRED",
            "machine_verifiable": False,
            "candidate_layers": sorted(CAN_IMPEDANCE_CANDIDATE_LAYERS),
            "note": "Layer choice and aggregate length do not prove 120-ohm differential impedance.",
        },
        "can_via_discontinuities": {
            "status": "OPEN_LAYOUT_REVIEW_REQUIRED" if any(can_vias.values()) else "NOT_PRESENT",
            "machine_verifiable": True,
            "via_count_by_net": can_vias,
        },
        "can_pair_coupling_and_stub_geometry": {
            "status": "OPEN_LAYOUT_REVIEW_REQUIRED",
            "machine_verifiable": False,
            "note": (
                "Branched CAN totals are not differential length; review coupled runs and connector, TVS, "
                "testpoint, and termination stubs manually."
            ),
        },
        "can_branched_path_correspondence": {
            "status": "OPEN_LAYOUT_REVIEW_REQUIRED",
            "machine_verifiable": False,
            "note": (
                "Branch presence and layer parity do not prove matching endpoint paths; compare each CANH/CANL "
                "connector, protection, testpoint, and termination branch manually."
            ),
        },
        "can_testpoint_stub_geometry": {
            "status": "OPEN_LAYOUT_REVIEW_REQUIRED" if not can_testpoint_pass else "MACHINE_CHECKED_SHORT_STUB",
            "machine_verifiable": True,
            "note": (
                "TP6/TP7 are constrained to short, same-layer, paired probe branches; differential coupling and "
                "probe loading still require oscilloscope review."
            ),
        },
        "can_reference_plane_continuity": {
            "status": "OPEN_LAYOUT_REVIEW_REQUIRED",
            "machine_verifiable": False,
            "note": (
                "Candidate signal layers do not prove a continuous adjacent GND_CAN_ISO reference plane; "
                "review plane coverage and return-path discontinuities manually."
            ),
        },
        "oscillator_return_path_and_load": {
            "status": "OPEN_MANUAL_REVIEW_REQUIRED",
            "machine_verifiable": False,
            "note": "Top-layer routing and zero vias do not prove crystal load, return-path, or EMI margin.",
        },
        "u3_microvia_fabrication": {
            "status": "OPEN_SUPPLIER_DFM_REQUIRED",
            "machine_verifiable": False,
            "note": (
                "U3 uses 0.45/0.15 mm F.Cu-to-In1.Cu laser microvias in its exposed pad. The supplier must "
                "approve copper filling, capping, planarization, registration, and assembly voiding controls."
            ),
        },
        "raw_can_blind_via_fabrication": {
            "status": "OPEN_SUPPLIER_DFM_REQUIRED",
            "machine_verifiable": False,
            "note": (
                "CANH_RAW and CANL_RAW use matched 0.60/0.30 mm F.Cu-to-In3.Cu blind vias. The supplier must "
                "approve controlled-depth drilling, aspect ratio, registration, plating reliability, lamination "
                "sequence, and the resulting impedance discontinuity."
            ),
        },
        "u7_isolated_power_safety_suitability": {
            "status": "OPEN_SAFETY_AND_VENDOR_REVIEW_REQUIRED",
            "machine_verifiable": False,
            "board_pad_edge_clearance_mm": u7_keepout_details.get("pad_edge_clearance_mm"),
            "note": (
                "The full-layer board keepout preserves the available U7 pad-row gap, but the MEJ1S0305SC "
                "candidate specifies only 2 mm creepage/clearance and 200 Vrms working voltage. It cannot close "
                "the 8 mm reinforced system-isolation target without a replacement or documented safety decision."
            ),
        },
    }
    warnings = [name for name, risk in risks.items() if str(risk["status"]).startswith("OPEN_")]
    hard_gate_pass = all(checks.values())
    net_segment_counts: dict[str, int] = {}
    net_via_counts: dict[str, int] = {}
    for segment in segments:
        net = segment["net"] or "<UNNAMED>"
        net_segment_counts[net] = net_segment_counts.get(net, 0) + 1
    for via in vias:
        net = via["net"] or "<UNNAMED>"
        net_via_counts[net] = net_via_counts.get(net, 0) + 1
    return {
        "pass": hard_gate_pass,
        "hard_gate_pass": hard_gate_pass,
        "status": "LAYOUT_HARD_GATES_PASS_RISKS_OPEN" if hard_gate_pass else "LAYOUT_HARD_GATES_FAIL",
        "board": str(path),
        "checks": checks,
        "details": {
            "high_current_widths_with_bounded_neckdowns": width_details,
            "reference_layer_net_categories": layer_details,
            "oscillator_fcu_only_no_vias": oscillator_details,
            "can_in1_reference_zone_declared": can_reference_zone_details,
            "u6_full_copper_isolation_keepout": u6_keepout_details,
            "u7_full_copper_isolation_keepout": u7_keepout_details,
            "u2_source_return_via_arrays": u2_via_array_details,
            "u3_exposed_pad_thermal_microvia_array": u3_thermal_via_details,
            "u3_output_parallel_transfer_vias": u3_output_via_details,
            "raw_can_matched_fcu_in3_blind_vias": raw_can_blind_via_details,
            "can_candidate_layers_and_pair_delta": can_details,
            "can_testpoint_stub_geometry": can_testpoint_details,
        },
        "risks": risks,
        "warnings": warnings,
        "metrics": {
            "segment_count": len(segments),
            "via_count": len(vias),
            "zone_count": len(zones),
            "net_segment_counts": dict(sorted(net_segment_counts.items())),
            "net_via_counts": dict(sorted(net_via_counts.items())),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit deterministic PCB placement and routing constraints")
    parser.add_argument("--board", type=Path, default=DEFAULT_BOARD, help="path to a KiCad PCB file")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="JSON report path")
    args = parser.parse_args()
    report = audit(args.board)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["hard_gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
