from __future__ import annotations

import csv
import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "hardware/pcb/tools"


def load_generator(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    path = TOOLS / "generate_expected_connectivity.py"
    spec = importlib.util.spec_from_file_location("expected_connectivity_generator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_output_matches_controlled_design_data(monkeypatch, tmp_path: Path) -> None:
    generator = load_generator(monkeypatch)
    output = tmp_path / "expected-connectivity.json"

    generator.write_expected_connectivity(output)

    raw = output.read_text(encoding="utf-8")
    generated = json.loads(raw)
    controlled = {component.reference: component.pins for component in generator.COMPONENTS}
    assert generated == controlled
    assert raw == json.dumps(generated, indent=2) + "\n"
    assert list(generated) == sorted(generated, key=generator.natural_key)
    for pins in generated.values():
        assert list(pins) == sorted(pins, key=generator.natural_key)


def test_recent_explicit_connectivity_is_preserved(monkeypatch, tmp_path: Path) -> None:
    generator = load_generator(monkeypatch)
    output = tmp_path / "expected-connectivity.json"

    generator.write_expected_connectivity(output)
    generated = json.loads(output.read_text(encoding="utf-8"))

    assert generated["U3"]["25"] == "GND"
    assert generated["R59"] == {"1": "12V_ISO", "2": "U3_UVLO"}
    assert generated["R60"] == {"1": "U3_UVLO", "2": "GND"}
    assert generated["C44"] == {"1": "5V_CAN_ISO", "2": "GND_CAN_ISO"}


def test_populated_connector_pinout_matches_controlled_design_data(monkeypatch) -> None:
    generator = load_generator(monkeypatch)
    controlled = {component.reference: component.pins for component in generator.COMPONENTS}
    with (ROOT / "hardware/pcb/connector-pinout.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    checked = 0
    for row in rows:
        if row["reference"] not in controlled:
            continue
        expected = controlled[row["reference"]][row["pin"]]
        assert row["net"] == ("NC" if expected is None else expected)
        checked += 1

    assert checked == len(rows)
    assert controlled["J4"]["8"] == controlled["U5"]["91"] == "JETSON_ENABLE_REQ"
    assert controlled["U5"]["53"] == controlled["K1"]["3"] == "MOTOR_ENABLE_REQ"
    with (ROOT / "hardware/pcb/connectors.csv").open(newline="", encoding="utf-8") as handle:
        j4_summary = next(row for row in csv.DictReader(handle) if row["reference"] == "J4")
    assert "JETSON_ENABLE_REQ" in j4_summary["signals"]
    assert "MOTOR_ENABLE_REQ" not in j4_summary["signals"]


def test_exported_schematic_netlist_matches_controlled_design_data(monkeypatch) -> None:
    generator = load_generator(monkeypatch)
    controlled = {component.reference: component.pins for component in generator.COMPONENTS}
    root = ET.parse(ROOT / "hardware/pcb/generated/controller.net").getroot()
    exported: dict[str, dict[str, str | None]] = {}

    for net in root.findall(".//net"):
        name = net.attrib["name"]
        value = None if name.startswith("unconnected-") else name.removeprefix("/")
        for node in net.findall("node"):
            exported.setdefault(node.attrib["ref"], {})[node.attrib["pin"]] = value

    assert exported == controlled
    assert exported["J4"]["8"] == "JETSON_ENABLE_REQ"
    assert exported["U5"]["53"] == "MOTOR_ENABLE_REQ"
    assert exported["U5"]["91"] == "JETSON_ENABLE_REQ"
