#!/usr/bin/env python3
"""Read-only host prerequisite report for the full development container."""

from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess


def command_output(command: list[str]) -> tuple[int, str]:
    executable = shutil.which(command[0])
    if not executable:
        return 127, "not installed"
    result = subprocess.run([executable, *command[1:]], capture_output=True, text=True, timeout=15, check=False)
    return result.returncode, (result.stdout or result.stderr).strip()


def first_version(value: str) -> tuple[int, ...]:
    match = re.search(r"\b(\d+(?:\.\d+)+)", value)
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-gpu", action="store_true")
    args = parser.parse_args()
    docker_rc, docker = command_output(["docker", "version", "--format", "{{.Client.Version}}"])
    compose_rc, compose = command_output(["docker", "compose", "version", "--short"])
    toolkit_rc, toolkit = command_output(["nvidia-ctk", "--version"])
    gpu_rc, gpu = command_output(
        ["nvidia-smi", "--query-gpu=name,driver_version,compute_cap", "--format=csv,noheader"]
    )
    gpu_rows = [line for line in gpu.splitlines() if "," in line]
    core_checks = {
        "platform_linux_amd64": platform.system() == "Linux" and platform.machine() == "x86_64",
        "docker_cli": docker_rc == 0 or docker != "not installed",
        "docker_daemon": docker_rc == 0,
        "compose_at_least_2_30": compose_rc == 0 and first_version(compose) >= (2, 30),
    }
    gpu_checks = {
        "container_toolkit_at_least_1_17": toolkit_rc == 0 and first_version(toolkit) >= (1, 17),
        "nvidia_driver_at_least_570_26": gpu_rc == 0 and bool(gpu_rows) and all(
            first_version(line.split(",")[1]) >= (570, 26) for line in gpu_rows
        ),
    }
    required_checks = {**core_checks, **gpu_checks} if args.require_gpu else core_checks
    report = {
        "schema_version": "workbench-container-host-doctor-v1",
        "status": "PASS" if all(required_checks.values()) else "NOT_EXECUTED",
        "core_status": "PASS" if all(core_checks.values()) else "NOT_EXECUTED",
        "gpu_status": "PASS" if all(gpu_checks.values()) else "NOT_EXECUTED",
        "gpu_required": args.require_gpu,
        "checks": {**core_checks, **gpu_checks},
        "docker": docker,
        "compose": compose,
        "container_toolkit": toolkit,
        "gpu": gpu,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
