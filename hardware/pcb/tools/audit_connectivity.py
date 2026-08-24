from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "kicad/controller.kicad_pcb"
EXPECTED = ROOT / "expected-connectivity.json"
OUT = ROOT / "generated/connectivity_report.json"


def blocks(text: str, token: str) -> list[str]:
    result = []
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


def board_connectivity() -> dict[str, dict[str, str | None]]:
    text = BOARD.read_text(encoding="utf-8")
    connectivity = {}
    for footprint in blocks(text, "(footprint"):
        reference_match = re.search(r'\(property "Reference" "([^"]+)"', footprint)
        if not reference_match:
            continue
        pins = {}
        for pad in blocks(footprint, "(pad"):
            pad_match = re.match(r'\(pad "([^"]*)"', pad)
            if not pad_match or not pad_match.group(1):
                continue
            net_match = re.search(r'\(net (?:\d+ )?"([^"]+)"\)', pad)
            pins[pad_match.group(1)] = net_match.group(1) if net_match else None
        connectivity[reference_match.group(1)] = pins
    return connectivity


def logical_connectivity(
    physical: dict[str, dict[str, str | None]],
) -> dict[str, dict[str, str | None]]:
    logical = {reference: dict(pins) for reference, pins in physical.items()}
    for reference in ("Q1", "Q2"):
        if reference not in physical:
            continue
        pins = physical[reference]
        logical[reference] = {
            "1": pins.get("4"),
            "2": pins.get("1"),
            "3": pins.get("5"),
        }
    return logical


def audit() -> dict[str, object]:
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    physical = board_connectivity()
    actual = logical_connectivity(physical)
    mismatches = []
    for reference, expected_pins in expected.items():
        if reference not in actual:
            mismatches.append({"reference": reference, "error": "missing footprint"})
            continue
        for pin, expected_net in expected_pins.items():
            actual_net = actual[reference].get(pin, "MISSING_PAD")
            if actual_net != expected_net:
                mismatches.append({"reference": reference, "pin": pin, "expected": expected_net, "actual": actual_net})

    domain_checks = {
        "input_protection_stages_are_distinct": len(
            {physical["F1"]["1"], physical["F1"]["2"], physical["Q2"]["5"], physical["RS1"]["2"]}
        )
        == 4,
        "back_to_back_fets_share_only_the_source_node": physical["Q1"]["1"]
        == physical["Q1"]["2"]
        == physical["Q1"]["3"]
        == physical["Q2"]["1"]
        == physical["Q2"]["2"]
        == physical["Q2"]["3"]
        == "FET_COMMON"
        and physical["Q1"]["5"] != physical["Q2"]["5"],
        "ltc4368_sense_resistor_is_kelvin_named": physical["U1"]["9"] == physical["RS1"]["1"] == "INPUT_SENSE"
        and physical["U1"]["8"] == physical["RS1"]["2"] == "VBAT_PROTECTED",
        "can_isolated_ground_is_distinct": physical["U6"]["2"] != physical["U6"]["9"],
        "can_isolated_supply_is_distinct": physical["U6"]["1"] != physical["U6"]["11"],
        "software_request_is_not_safe_output": physical["K1"]["3"] != physical["K2"]["4"],
        "both_estop_channels_are_independent": physical["J10"]["1"] == physical["J10"]["3"] == "ESTOP_12V"
        and physical["J10"]["2"] != physical["J10"]["4"],
        "both_manual_reset_returns_are_independent": physical["J12"]["2"] != physical["J12"]["4"],
        "estop_diagnostics_are_open_collector": physical["U8"]["16"] == physical["R49"]["2"] == "ESTOP_A_MON"
        and physical["U8"]["14"] == physical["R50"]["2"] == "ESTOP_B_MON"
        and physical["U8"]["15"] == physical["U8"]["13"] == "GND"
        and physical["R49"]["1"] == physical["R50"]["1"] == "3V3_LOGIC",
    }
    return {
        "status": "CONNECTIVITY_PASS" if not mismatches and all(domain_checks.values()) else "CONNECTIVITY_FAIL",
        "checked_references": sorted(expected),
        "checked_pin_count": sum(len(pins) for pins in expected.values()),
        "domain_checks": domain_checks,
        "mismatches": mismatches,
        "pass": not mismatches and all(domain_checks.values()),
    }


def main() -> None:
    report = audit()
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["pass"]:
        raise SystemExit("PCB connectivity audit failed")


if __name__ == "__main__":
    main()
