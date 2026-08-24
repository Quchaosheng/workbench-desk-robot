from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "hardware/pcb/tools"


def load_design_data():
    path = TOOLS / "design_data.py"
    spec = importlib.util.spec_from_file_location("u3_design_data", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def components_by_reference(module):
    return {component.reference: component for component in module.COMPONENTS}


def test_u3_uvlo_divider_is_valid_for_a_12v_rail() -> None:
    components = components_by_reference(load_design_data())
    u3 = components["U3"]
    upper = components["R59"]
    lower = components["R60"]

    assert u3.pins["6"] == "U3_UVLO"
    assert upper.value == "73.2k 1%"
    assert upper.pins == {"1": "12V_ISO", "2": "U3_UVLO"}
    assert lower.value == "10.0k 1%"
    assert lower.pins == {"1": "U3_UVLO", "2": "GND"}

    divider_ratio = 10.0 / (73.2 + 10.0)
    assert 9.5 < 1.2 / divider_ratio < 10.5
    assert 9.0 < 1.122 / divider_ratio < 10.0
    assert 14.4 * divider_ratio < 5.5


def test_u3_shdn_and_powerpad_are_explicitly_safe() -> None:
    module = load_design_data()
    components = components_by_reference(module)
    u3 = components["U3"]
    symbol_pins = {pin.number: pin.name for pin in module.CUSTOM_SYMBOLS["TPS26633RGE"][1]}

    assert u3.pins["12"] == "3V3_LOGIC"
    assert u3.pins["25"] == "GND"
    assert symbol_pins["25"] == "PowerPAD"
    assert set(u3.pins) == set(symbol_pins)


def test_board_generator_has_no_u3_only_powerpad_override() -> None:
    source = (TOOLS / "generate_kicad_board.py").read_text(encoding="utf-8")
    assert 'if reference == "U3"' not in source
    assert 'mapping["25"] = "GND"' not in source
