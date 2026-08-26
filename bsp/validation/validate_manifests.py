"""Validate the repository-side robot BSP manifests."""

from __future__ import annotations

import csv
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def validate_camera_manifest(camera: dict) -> list[str]:
    errors: list[str] = []
    if camera.get("quantity_per_robot") != 1 or camera.get("selection", {}).get("model") != "D435":
        errors.append("prototype BSP requires exactly one D435 head camera")
    if camera.get("selection", {}).get("interface") != "USB_3":
        errors.append("head RGB-D camera must use the selected USB 3 boundary")
    if camera.get("boundaries", {}).get("physical_evidence_ready") is not False:
        errors.append("camera physical evidence must remain false before calibration and bring-up")
    return errors


def validate_manifests(manifest: dict, compatibility: dict, bringup: dict) -> list[str]:
    errors: list[str] = []

    if manifest["linux_board"].get("model") != "NVIDIA_JETSON_ORIN_NANO_SUPER_DEVELOPER_KIT_8GB":
        errors.append("unexpected Linux board selection")
    controllers = manifest.get("controllers", [])
    if len(controllers) != 6:
        errors.append("exactly six controller domains are required")
    ids = [controller.get("id") for controller in controllers]
    node_ids = [controller.get("node_id") for controller in controllers]
    if len(set(ids)) != len(ids):
        errors.append("controller domain IDs must be unique")
    if len(set(node_ids)) != len(node_ids):
        errors.append("controller node IDs must be unique")
    safety = next((controller for controller in controllers if controller.get("id") == "MCU-SAFETY"), None)
    if not safety or safety.get("independent_reset_domain") is not True:
        errors.append("MCU-SAFETY must have an independent reset domain")
    if set(compatibility.get("controllers", {})) != set(ids):
        errors.append("firmware compatibility domains do not match board domains")
    if bringup.get("status") != "plan_not_executed":
        errors.append("bring-up status must remain plan_not_executed")
    if any(test.get("result") != "NOT_EXECUTED" for test in bringup.get("tests", [])):
        errors.append("physical bring-up results must remain NOT_EXECUTED")
    return errors


def validate() -> list[str]:
    manifest = yaml.safe_load((ROOT / "bsp/board-manifest.yaml").read_text(encoding="utf-8"))
    compatibility = yaml.safe_load((ROOT / "bsp/firmware/compatibility.yaml").read_text(encoding="utf-8"))
    bringup = yaml.safe_load((ROOT / "bsp/validation/bringup-plan.yaml").read_text(encoding="utf-8"))
    errors = validate_manifests(manifest, compatibility, bringup)
    kernel_config = (ROOT / "bsp/linux/robot_bsp.config").read_text(encoding="utf-8")
    required_symbols = {
        "CONFIG_CAN=y",
        "CONFIG_CAN_RAW=y",
        "CONFIG_CAN_DEV=y",
        "CONFIG_WATCHDOG=y",
        "CONFIG_PSTORE=y",
        "CONFIG_VIDEO_DEV=y",
        "CONFIG_VIDEO_V4L2=y",
        "CONFIG_USB_VIDEO_CLASS=y",
    }
    missing_symbols = sorted(symbol for symbol in required_symbols if symbol not in kernel_config.splitlines())
    if missing_symbols:
        errors.append(f"kernel config missing required symbols: {', '.join(missing_symbols)}")
    services = yaml.safe_load((ROOT / "bsp/rootfs/services.yaml").read_text(encoding="utf-8"))
    if services.get("default_motion_state") != "inhibited":
        errors.append("rootfs must boot with motion inhibited")
    if any(service.get("safety_authority") is not False for service in services.get("services", {}).values()):
        errors.append("no Linux service may own safety authority")
    with (ROOT / "bsp/procurement/selection-register.csv").open(newline="", encoding="utf-8") as handle:
        selections = list(csv.DictReader(handle))
    if len(selections) != 8 or len({selection["item_id"] for selection in selections}) != 8:
        errors.append("procurement register must contain eight unique BSP selections")
    if any(not selection["required_closure"].strip() for selection in selections):
        errors.append("every BSP selection requires an explicit closure action")
    camera = yaml.safe_load((ROOT / "bsp/sensors/camera-head.yaml").read_text(encoding="utf-8"))
    errors.extend(validate_camera_manifest(camera))
    return errors


if __name__ == "__main__":
    failures = validate()
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        raise SystemExit(1)
    print("BSP manifest validation passed")
