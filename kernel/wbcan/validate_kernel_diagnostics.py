"""Fail-closed validation for bounded wbcan kernel diagnostics."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "wbcan-kernel-diagnostics-v2"
WARNING_PATTERNS = (
    r"BUG:",
    r"WARNING:",
    r"lockdep",
    r"KCSAN:",
    r"KASAN:",
    r"UBSAN:",
    r"possible circular locking",
    r"soft lockup",
    r"hung task",
    r"refcount",
    r"use-after-free",
    r"sleeping function called from invalid context",
    r"RCU stall",
    r"can_change_state: oops, state did not change",
    r"Attempt to restart for bus-off recovery, but carrier is OK",
)


def validate_report(report: object) -> None:
    if not isinstance(report, dict):
        raise ValueError("diagnostic report must be an object")
    if report.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("diagnostic report schema_version is invalid")
    if report.get("scope") != "virtual-wbcan-kernel-job":
        raise ValueError("diagnostic report scope is invalid")
    if report.get("result") not in {"PASS", "FAIL", "NOT_EXECUTED"}:
        raise ValueError("diagnostic report result is invalid")
    for name in ("kernel", "marker", "dmesg_path", "slabinfo_path", "meminfo_path"):
        if not isinstance(report.get(name), str) or not report[name]:
            raise ValueError(f"diagnostic report requires {name}")
    warnings = report.get("warnings")
    if not isinstance(warnings, list) or any(not isinstance(item, str) or not item for item in warnings):
        raise ValueError("diagnostic report warnings must be a list of strings")
    if report["result"] == "PASS" and warnings:
        raise ValueError("passing diagnostic report cannot contain warnings")
    if report["result"] == "FAIL" and not warnings:
        raise ValueError("failed diagnostic report must contain warning matches")
    if report["result"] == "NOT_EXECUTED" and warnings:
        raise ValueError("not-executed diagnostic report cannot contain warning matches")
    for name in ("dmesg_bytes", "scoped_dmesg_bytes", "slabinfo_bytes", "meminfo_bytes"):
        if not isinstance(report.get(name), int) or isinstance(report[name], bool) or report[name] < 0:
            raise ValueError(f"diagnostic report has invalid {name}")
    snapshots = report.get("resource_snapshots")
    if not isinstance(snapshots, dict):
        raise ValueError("diagnostic report requires resource_snapshots")
    for phase in ("before", "after"):
        snapshot = snapshots.get(phase)
        if not isinstance(snapshot, dict):
            raise ValueError(f"diagnostic report requires {phase} resource snapshot")
        for name in ("slabinfo_path", "meminfo_path"):
            if not isinstance(snapshot.get(name), str) or not snapshot[name]:
                raise ValueError(f"{phase} resource snapshot requires {name}")
        for name in ("slabinfo_bytes", "meminfo_bytes"):
            value = snapshot.get(name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{phase} resource snapshot has invalid {name}")
    after = snapshots["after"]
    if (
        after["slabinfo_path"] != report["slabinfo_path"]
        or after["meminfo_path"] != report["meminfo_path"]
        or after["slabinfo_bytes"] != report["slabinfo_bytes"]
        or after["meminfo_bytes"] != report["meminfo_bytes"]
    ):
        raise ValueError("diagnostic after snapshot disagrees with top-level fields")
    before = snapshots["before"]
    if before["slabinfo_path"] == after["slabinfo_path"] or before["meminfo_path"] == after["meminfo_path"]:
        raise ValueError("diagnostic before and after snapshots must be distinct")
    if report["result"] == "NOT_EXECUTED":
        reason = report.get("not_executed_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("not-executed diagnostic report requires a reason")


def scan_dmesg(text: str) -> list[str]:
    warnings: list[str] = []
    for line in text.splitlines():
        if any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in WARNING_PATTERNS):
            warnings.append(line.strip())
    return warnings


def build_report(
    dmesg: Path,
    slabinfo: Path,
    meminfo: Path,
    kernel: str,
    marker: str,
    *,
    before_slabinfo: Path | None = None,
    before_meminfo: Path | None = None,
) -> dict[str, Any]:
    if before_slabinfo is None or before_meminfo is None:
        raise ValueError("before slabinfo and meminfo snapshots are required")
    dmesg_text = dmesg.read_text(encoding="utf-8", errors="replace")
    slabinfo_text = slabinfo.read_text(encoding="utf-8", errors="replace")
    meminfo_text = meminfo.read_text(encoding="utf-8", errors="replace")
    before_slabinfo_text = before_slabinfo.read_text(encoding="utf-8", errors="replace")
    before_meminfo_text = before_meminfo.read_text(encoding="utf-8", errors="replace")
    if not marker or marker not in dmesg_text:
        raise ValueError("diagnostic marker is missing from dmesg")
    scoped_dmesg = dmesg_text.split(marker, 1)[1]
    warnings = scan_dmesg(scoped_dmesg)
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "virtual-wbcan-kernel-job",
        "result": "FAIL" if warnings else "PASS",
        "kernel": kernel,
        "marker": marker,
        "dmesg_path": str(dmesg),
        "slabinfo_path": str(slabinfo),
        "meminfo_path": str(meminfo),
        "dmesg_bytes": len(dmesg_text.encode("utf-8")),
        "scoped_dmesg_bytes": len(scoped_dmesg.encode("utf-8")),
        "slabinfo_bytes": len(slabinfo_text.encode("utf-8")),
        "meminfo_bytes": len(meminfo_text.encode("utf-8")),
        "resource_snapshots": {
            "before": {
                "slabinfo_path": str(before_slabinfo),
                "meminfo_path": str(before_meminfo),
                "slabinfo_bytes": len(before_slabinfo_text.encode("utf-8")),
                "meminfo_bytes": len(before_meminfo_text.encode("utf-8")),
            },
            "after": {
                "slabinfo_path": str(slabinfo),
                "meminfo_path": str(meminfo),
                "slabinfo_bytes": len(slabinfo_text.encode("utf-8")),
                "meminfo_bytes": len(meminfo_text.encode("utf-8")),
            },
        },
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dmesg", type=Path)
    parser.add_argument("--slabinfo", type=Path)
    parser.add_argument("--meminfo", type=Path)
    parser.add_argument("--before-slabinfo", type=Path)
    parser.add_argument("--before-meminfo", type=Path)
    parser.add_argument("--kernel")
    parser.add_argument("--marker")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--validate-report", type=Path)
    args = parser.parse_args()
    if args.validate_report is not None:
        validate_report(json.loads(args.validate_report.read_text(encoding="utf-8")))
        print(f"kernel diagnostic report valid: {args.validate_report}")
        return 0
    if (
        not args.dmesg
        or not args.slabinfo
        or not args.meminfo
        or not args.before_slabinfo
        or not args.before_meminfo
        or not args.kernel
        or not args.report
        or not args.marker
    ):
        parser.error(
            "--dmesg, --slabinfo, --meminfo, --before-slabinfo, --before-meminfo, "
            "--kernel, --marker, and --report are required"
        )
    report = build_report(
        args.dmesg,
        args.slabinfo,
        args.meminfo,
        args.kernel,
        args.marker,
        before_slabinfo=args.before_slabinfo,
        before_meminfo=args.before_meminfo,
    )
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    validate_report(report)
    if report["result"] != "PASS":
        raise SystemExit(f"kernel diagnostic warnings found: {len(report['warnings'])}")
    print(f"kernel diagnostic report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
