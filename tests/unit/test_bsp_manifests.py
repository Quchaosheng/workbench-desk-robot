from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml

from bsp.validation.check_readiness import BLOCKED_STATUS, READY_STATUS, check, validate_readiness
from bsp.validation.validate_image_inputs import validate_image_inputs
from bsp.validation.validate_manifests import (
    validate,
    validate_camera_deployment,
    validate_camera_manifest,
    validate_manifests,
)

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


def test_composite_camera_cannot_use_one_video_device_alias() -> None:
    camera = yaml.safe_load((ROOT / "bsp/sensors/camera-head.yaml").read_text(encoding="utf-8"))
    changed = deepcopy(camera)
    changed["device_identity"]["single_video_device_symlink"] = "/dev/workbench-camera-head"

    errors = validate_camera_manifest(changed)

    assert "D435 must not use one shared video-device symlink" in errors


def test_unresolved_camera_deployment_cannot_be_enabled() -> None:
    deployment = yaml.safe_load((ROOT / "bsp/rootfs/camera-head-deployment.yaml").read_text(encoding="utf-8"))
    changed = deepcopy(deployment)
    changed["installable"] = True
    unit = (ROOT / "bsp/rootfs/systemd/robot-camera-head.service.in").read_text(encoding="utf-8")
    launcher = (ROOT / "bsp/rootfs/libexec/camera-head-launch").read_text(encoding="utf-8")
    environment = (ROOT / "bsp/rootfs/camera-head.env.example").read_text(encoding="utf-8")

    errors = validate_camera_deployment(changed, unit, launcher, environment)

    assert "camera deployment with unresolved selections must not be installable" in errors


def test_camera_service_must_reject_placeholder_serial() -> None:
    deployment = yaml.safe_load((ROOT / "bsp/rootfs/camera-head-deployment.yaml").read_text(encoding="utf-8"))
    unit = (ROOT / "bsp/rootfs/systemd/robot-camera-head.service.in").read_text(encoding="utf-8")
    launcher = (ROOT / "bsp/rootfs/libexec/camera-head-launch").read_text(encoding="utf-8")
    environment = (ROOT / "bsp/rootfs/camera-head.env.example").read_text(encoding="utf-8")

    errors = validate_camera_deployment(
        deployment, unit.replace("ExecStartPre=", "# removed=", 2), launcher, environment
    )

    assert "camera systemd unit must reject the placeholder serial" in errors


def load_readiness() -> dict:
    return yaml.safe_load((ROOT / "bsp/readiness.yaml").read_text(encoding="utf-8"))


def test_readiness_rejects_missing_or_unknown_controlled_gate() -> None:
    changed = deepcopy(load_readiness())
    changed["gates"].pop()
    changed["gates"][0]["id"] = "BSP-GATE-UNCONTROLLED"

    assert "BSP readiness must contain the exact nine controlled gates" in validate_readiness(changed)


def test_readiness_rejects_evidence_outside_repository(tmp_path: Path) -> None:
    changed = deepcopy(load_readiness())
    changed["gates"][0]["evidence"] = "../outside.txt"

    errors = validate_readiness(changed, tmp_path / "repo")

    assert "BSP-GATE-ARCH claims PASS without repository evidence" in errors


def test_readiness_rejects_directory_as_pass_evidence(tmp_path: Path) -> None:
    changed = deepcopy(load_readiness())
    root = tmp_path / "repo"
    (root / "evidence").mkdir(parents=True)
    changed["gates"][0]["evidence"] = "evidence"

    errors = validate_readiness(changed, root)

    assert "BSP-GATE-ARCH claims PASS without repository evidence" in errors


def test_readiness_release_flag_and_package_status_follow_all_gates(tmp_path: Path) -> None:
    changed = deepcopy(load_readiness())
    root = tmp_path / "repo"
    evidence = root / "evidence.txt"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("controlled evidence\n", encoding="ascii")
    for gate in changed["gates"]:
        gate["status"] = "PASS"
        gate["evidence"] = "evidence.txt"
    changed["physical_release_ready"] = True
    changed["status"] = READY_STATUS

    assert validate_readiness(changed, root) == []

    changed["gates"][0]["status"] = "BLOCKED"
    assert "physical_release_ready must equal the all-gates-PASS result" in validate_readiness(changed, root)
    changed["physical_release_ready"] = False
    assert f"BSP package status must be {BLOCKED_STATUS}" in validate_readiness(changed, root)


def load_image_inputs() -> dict:
    return yaml.safe_load((ROOT / "bsp/image/build-inputs.yaml").read_text(encoding="utf-8"))


def test_unresolved_image_inputs_are_valid_but_not_build_ready() -> None:
    manifest = load_image_inputs()

    assert manifest["build_ready"] is False
    assert manifest["status"] == "inputs_unresolved"
    assert validate_image_inputs(manifest) == []


def test_image_inputs_reject_premature_ready_or_insecure_source() -> None:
    manifest = deepcopy(load_image_inputs())
    manifest["build_ready"] = True
    manifest["status"] = "inputs_locked"
    manifest["inputs"]["jetpack"]["source"] = "http://vendor.invalid/jetpack"

    errors = validate_image_inputs(manifest)

    assert "jetpack source must use HTTPS" in errors
    assert "unresolved image inputs must block build_ready" in errors


def test_image_inputs_reject_path_escape_and_directory(tmp_path: Path) -> None:
    manifest = deepcopy(load_image_inputs())
    manifest["inputs"]["kernel"]["config"] = "../outside.config"
    manifest["inputs"]["rootfs"]["services"] = "bsp"
    (tmp_path / "repo/bsp").mkdir(parents=True)

    errors = validate_image_inputs(manifest, tmp_path / "repo")

    assert "kernel config must reference a repository file" in errors
    assert "rootfs services must reference a repository file" in errors


def test_image_outputs_cannot_exist_before_inputs_are_locked() -> None:
    manifest = deepcopy(load_image_inputs())
    digest = "a" * 64
    manifest["outputs"] = {
        "boot_image_sha256": digest,
        "rootfs_image_sha256": digest,
        "recovery_image_sha256": digest,
    }

    assert "built output hashes require build_ready inputs" in validate_image_inputs(manifest)
