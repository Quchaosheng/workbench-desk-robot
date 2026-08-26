from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml

from bsp.validation.validate_manifests import validate, validate_manifests

ROOT = Path(__file__).resolve().parents[2]


def load_manifests() -> tuple[dict, dict, dict]:
    board = yaml.safe_load((ROOT / "bsp/board-manifest.yaml").read_text(encoding="utf-8"))
    compatibility = yaml.safe_load((ROOT / "bsp/firmware/compatibility.yaml").read_text(encoding="utf-8"))
    bringup = yaml.safe_load((ROOT / "bsp/validation/bringup-plan.yaml").read_text(encoding="utf-8"))
    return board, compatibility, bringup


def test_bsp_manifests_are_consistent_and_fail_closed() -> None:
    assert validate() == []


def test_duplicate_node_id_and_nonindependent_safety_are_rejected() -> None:
    board, compatibility, bringup = load_manifests()
    changed = deepcopy(board)
    changed["controllers"][1]["node_id"] = changed["controllers"][0]["node_id"]
    changed["controllers"][-1]["independent_reset_domain"] = False

    errors = validate_manifests(changed, compatibility, bringup)

    assert "controller node IDs must be unique" in errors
    assert "MCU-SAFETY must have an independent reset domain" in errors


def test_physical_pass_without_evidence_is_rejected() -> None:
    board, compatibility, bringup = load_manifests()
    changed = deepcopy(bringup)
    changed["tests"][0]["result"] = "PASS"

    errors = validate_manifests(board, compatibility, changed)

    assert "physical bring-up results must remain NOT_EXECUTED" in errors
