#!/usr/bin/env python3
"""Check physical bring-up prerequisites without touching robot controls."""

import argparse
import json
import platform
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Workbench-1 hardware prerequisites")
    parser.add_argument("--can-interface", default="can0")
    parser.add_argument("--camera-device", default="/dev/video0")
    parser.add_argument("--estop-marker", type=Path, default=Path("/run/workbench/estop-ready"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    checks = {
        "linux": platform.system() == "Linux",
        "ip_command": shutil.which("ip") is not None,
        "can_interface": Path("/sys/class/net", args.can_interface).exists(),
        "camera_device": Path(args.camera_device).exists(),
        "estop_marker": args.estop_marker.is_file(),
    }
    payload = {
        "schema_version": 1,
        "status": "ready" if all(checks.values()) else "not_ready",
        "checks": checks,
        "safe_action": "No motor or CAN command was sent; resolve failed checks before bring-up.",
    }
    encoded = json.dumps(payload, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if payload["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
