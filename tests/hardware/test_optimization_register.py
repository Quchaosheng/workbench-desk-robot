from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_validator():
    path = ROOT / "hardware/release/tools/validate_optimization_register.py"
    spec = importlib.util.spec_from_file_location("optimization_register", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_rows() -> list[dict[str, str]]:
    with (ROOT / "hardware/release/hardware-optimization-register.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_optimization_register_is_complete_and_fail_closed() -> None:
    module = load_validator()
    report = module.validate(load_rows())
    assert report["pass"] is True
    assert report["row_count"] >= 20
    assert report["open_p0"]
    assert "OPT-COST-001" in report["open_p0"]


def test_optimization_register_rejects_missing_acceptance_contract() -> None:
    module = load_validator()
    rows = load_rows()
    rows[0]["acceptance_evidence"] = ""
    report = module.validate(rows)
    assert report["pass"] is False
    assert report["checks"]["owners_and_actions_present"] is False


def test_optimization_register_rejects_unknown_domain() -> None:
    module = load_validator()
    rows = load_rows()
    rows[0]["domain"] = "misc"
    report = module.validate(rows)
    assert report["pass"] is False
    assert report["checks"]["domains_controlled"] is False
