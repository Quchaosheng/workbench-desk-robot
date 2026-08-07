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


def audit() -> dict[str, object]:
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    actual = board_connectivity()
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
        "input_protection_stages_are_distinct": len({actual["F1"]["1"], actual["F1"]["2"], actual["U1"]["3"]}) == 3,
        "can_isolated_ground_is_distinct": actual["U6"]["2"] != actual["U6"]["6"],
        "can_isolated_supply_is_distinct": actual["U6"]["1"] != actual["U6"]["5"],
        "software_request_is_not_safe_output": actual["U8"]["3"] != actual["U8"]["4"],
        "both_estop_channels_are_independent": len({actual["J10"][str(pin)] for pin in range(1, 5)}) == 4,
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
