from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml

from bsp.validation.check_readiness import check
from bsp.validation.validate_manifests import validate, validate_camera_manifest, validate_manifests

ROOT = Path(__file__).resolve().parents[2]


def load_manifests() -> tuple[dict, dict, dict]:
    board = yaml.safe_load((ROOT / "bsp/board-manifest.yaml").read_text(encoding="utf-8"))
    compatibility = yaml.safe_load((ROOT / "bsp/firmware/compatibility.yaml").read_text(encoding="utf-8"))
    bringup = yaml.safe_load((ROOT / "bsp/validation/bringup-plan.yaml").read_text(encoding="utf-8"))
    return board, compatibility, bringup


def test_bsp_manifests_are_consistent_and_fail_closed() -> None:
    assert validate() == []
    assert check() == []


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


def test_camera_selection_drift_is_rejected() -> None:
    camera = yaml.safe_load((ROOT / "bsp/sensors/camera-head.yaml").read_text(encoding="utf-8"))
    changed = deepcopy(camera)
    changed["quantity_per_robot"] = 2
    changed["selection"]["model"] = "UNREVIEWED_CAMERA"
    changed["selection"]["interface"] = "USB_2"

    errors = validate_camera_manifest(changed)

    assert "prototype BSP requires exactly one D435 head camera" in errors
    assert "head RGB-D camera must use the selected USB 3 boundary" in errors


def test_camera_physical_evidence_cannot_be_claimed_before_bringup() -> None:
    camera = yaml.safe_load((ROOT / "bsp/sensors/camera-head.yaml").read_text(encoding="utf-8"))
    changed = deepcopy(camera)
    changed["boundaries"]["physical_evidence_ready"] = True

    errors = validate_camera_manifest(changed)

    assert "camera physical evidence must remain false before calibration and bring-up" in errors
