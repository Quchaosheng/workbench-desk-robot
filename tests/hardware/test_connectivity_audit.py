from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "hardware/pcb/tools/audit_connectivity.py"


def load_module():
    spec = importlib.util.spec_from_file_location("audit_connectivity", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_power_mosfet_footprint_pads_map_back_to_symbol_pins() -> None:
    module = load_module()
    physical = {
        "Q1": {
            "1": "FET_COMMON",
            "2": "FET_COMMON",
            "3": "FET_COMMON",
            "4": "FET_GATE",
            "5": "VBAT_FUSED",
        }
    }
    logical = module.logical_connectivity(physical)
    assert logical["Q1"] == {"1": "FET_GATE", "2": "FET_COMMON", "3": "VBAT_FUSED"}


def test_canonical_board_matches_controlled_connectivity() -> None:
    module = load_module()
    report = module.audit()
    assert report["pass"]
    assert report["mismatches"] == []
