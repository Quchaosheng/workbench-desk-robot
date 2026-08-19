#!/usr/bin/env python3
"""Measure bounded collector cost and emit synthetic snapshot evidence."""

import argparse
import json
import os
import platform
import resource
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from _paths import ROOT

sys.path.insert(0, str(ROOT / "libs" / "application"))

from workbench.application.monitoring import HealthSnapshotCollector, MetricSpec


def _matches(value: object, candidates: tuple[object, ...]) -> bool:
    return any(type(value) is type(candidate) and value == candidate for candidate in candidates)


def _healthy_value(spec: MetricSpec) -> bool | int | float | str:
    for value in spec.allowed_values:
        if not _matches(value, spec.fault_values + spec.degraded_values):
            return value
    if spec.value_type == "bool":
        return not _matches(True, spec.fault_values + spec.degraded_values)
    if spec.value_type == "str":
        return "none"
    value = max(0, spec.minimum) if spec.minimum is not None else 0
    if spec.maximum is not None:
        value = min(value, spec.maximum)
    return int(value) if spec.value_type == "int" else float(value)


def _complete(collector: HealthSnapshotCollector, observed_at: float) -> None:
    for spec in collector.metrics.registry.specs():
        collector.record(spec.name, _healthy_value(spec), source=spec.source, observed_at=observed_at)


def _proc_status() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        name, _, raw = line.partition(":")
        if name in {"VmRSS", "voluntary_ctxt_switches", "nonvoluntary_ctxt_switches"}:
            values[name] = int(raw.split()[0]) * (1_024 if name == "VmRSS" else 1)
    try:
        for line in Path("/proc/self/smaps_rollup").read_text(encoding="utf-8").splitlines():
            if line.startswith("Pss:"):
                values["Pss"] = int(line.split()[1]) * 1_024
                break
    except OSError:
        pass
    return values


def _snapshot_evidence(now: float) -> dict[str, dict]:
    complete = HealthSnapshotCollector(clock=lambda: now)
    _complete(complete, now)
    missing = HealthSnapshotCollector(clock=lambda: now)
    stale = HealthSnapshotCollector(clock=lambda: now)
    _complete(stale, now - 86_401)
    fault = HealthSnapshotCollector(clock=lambda: now)
    _complete(fault, now - 0.01)
    fault.record("safety.estop_channels_ok", False, source="safety_mcu", observed_at=now)
    return {
        "complete_synthetic": complete.snapshot().as_dict(),
        "missing_synthetic": missing.snapshot().as_dict(),
        "stale_synthetic": stale.snapshot().as_dict(),
        "fault_synthetic": fault.snapshot().as_dict(),
    }


def benchmark(iterations: int) -> dict:
    if not 1 <= iterations <= 1_000_000:
        raise ValueError("iterations must be between 1 and 1000000")
    now = time.monotonic()
    collector = HealthSnapshotCollector(clock=lambda: now)
    _complete(collector, now)
    for _ in range(min(iterations, 100)):
        collector.snapshot()

    before = _proc_status()
    threads_before = threading.active_count()
    cpu_started = time.process_time_ns()
    wall_started = time.perf_counter_ns()
    snapshot = None
    for _ in range(iterations):
        snapshot = collector.snapshot()
    wall_ns = time.perf_counter_ns() - wall_started
    cpu_ns = time.process_time_ns() - cpu_started
    after = _proc_status()
    assert snapshot is not None
    snapshot_json = json.dumps(snapshot.as_dict(), separators=(",", ":"), allow_nan=False).encode()
    prometheus = collector.metrics.export_prometheus().encode()
    max_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if platform.system() == "Linux":
        max_rss *= 1_024
    context_before = before.get("voluntary_ctxt_switches", 0) + before.get("nonvoluntary_ctxt_switches", 0)
    context_after = after.get("voluntary_ctxt_switches", 0) + after.get("nonvoluntary_ctxt_switches", 0)
    cpu_model = "unknown"
    try:
        cpu_model = next(
            line.partition(":")[2].strip()
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines()
            if line.startswith("model name")
        )
    except (OSError, StopIteration):
        pass
    return {
        "schema_version": 1,
        "captured_at": datetime.now(UTC).isoformat(),
        "evidence_class": "local_software",
        "result": "MEASURED_NO_TARGET_BUDGET",
        "provenance": "Local development host; not target Jetson or physical robot evidence.",
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "cpu_model": cpu_model,
        },
        "iterations": iterations,
        "resources": {
            "cpu_total_ns": cpu_ns,
            "cpu_ns_per_snapshot": cpu_ns / iterations,
            "wall_total_ns": wall_ns,
            "wall_ns_per_snapshot": wall_ns / iterations,
            "rss_before_bytes": before.get("VmRSS"),
            "rss_after_bytes": after.get("VmRSS"),
            "rss_peak_bytes": max_rss,
            "pss_after_bytes": after.get("Pss"),
            "scheduler_context_switches": context_after - context_before,
            "threads_before": threads_before,
            "threads_after": threading.active_count(),
            "periodic_wakeups_owned": 0,
        },
        "output": {
            "snapshot_json_bytes": len(snapshot_json),
            "prometheus_text_bytes": len(prometheus),
        },
        "snapshots": _snapshot_evidence(now),
        "target_hardware_measurement": "NOT_EXECUTED",
        "physical_source_validation": "NOT_EXECUTED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = benchmark(args.iterations)
    encoded = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
