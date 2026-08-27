#!/usr/bin/env python3
"""Measure bounded userspace-observed TX-to-RX latency on virtual wbcan."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import select
import socket
import statistics
import struct
import threading
import time
from pathlib import Path
from typing import Any

FRAME = struct.Struct("=IB3x8s")
SCHEMA_VERSION = "wbcan-latency-report-v2"
MIN_SAMPLES = 10
MAX_SAMPLES = 100_000


def percentile(values: list[int], percent: int) -> int:
    if not values:
        raise ValueError("latency samples must not be empty")
    if not 0 <= percent <= 100:
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(values)
    index = max(0, (len(ordered) * percent + 99) // 100 - 1)
    return ordered[index]


def summarize(samples_ns: list[int], deadline_ns: int | None) -> dict[str, int | str | None]:
    if any(not isinstance(sample, int) or isinstance(sample, bool) or sample < 0 for sample in samples_ns):
        raise ValueError("latency samples must be non-negative integers")
    if not samples_ns:
        raise ValueError("latency samples must not be empty")
    return {
        "p50_ns": percentile(samples_ns, 50),
        "p95_ns": percentile(samples_ns, 95),
        "p99_ns": percentile(samples_ns, 99),
        "max_ns": max(samples_ns),
        "jitter_definition": "population-standard-deviation-ns",
        "jitter_ns": round(statistics.pstdev(samples_ns)),
        "deadline_ns": deadline_ns,
        "missed_deadline_count": 0 if deadline_ns is None else sum(sample > deadline_ns for sample in samples_ns),
    }


def preemption_model() -> str:
    for path in (Path("/sys/kernel/realtime"), Path("/sys/kernel/debug/sched/preempt")):
        try:
            value = path.read_text(encoding="ascii").strip()
        except OSError:
            continue
        if value:
            return value
    return "unknown"


def kernel_config_hash() -> str:
    candidates = (Path("/proc/config.gz"), Path(f"/boot/config-{platform.release()}"))
    for path in candidates:
        try:
            data = path.read_bytes()
        except OSError:
            continue
        return hashlib.sha256(data).hexdigest()
    return "unavailable"


def validate_report(report: object) -> None:
    if not isinstance(report, dict):
        raise ValueError("latency report must be an object")
    if report.get("schema_version") != SCHEMA_VERSION or report.get("scope") != "virtual-wbcan-userspace":
        raise ValueError("latency report schema or scope is invalid")
    if report.get("result") not in {"PASS", "FAIL", "NOT_EXECUTED"}:
        raise ValueError("latency report result is invalid")
    for name in ("interface", "commit", "kernel", "kernel_config_sha256", "preemption_model", "clock"):
        if not isinstance(report.get(name), str) or not report[name]:
            raise ValueError(f"latency report requires {name}")
    if report.get("clock") != "monotonic_ns":
        raise ValueError("latency report clock must be monotonic_ns")
    if report.get("load_profile") not in {"idle", "status-readers"}:
        raise ValueError("latency report load_profile is invalid")
    for name in ("cpu_count", "warmup_count", "sample_count", "message_size", "can_id"):
        if not isinstance(report.get(name), int) or isinstance(report[name], bool) or report[name] < 0:
            raise ValueError(f"latency report has invalid {name}")
    affinity = report.get("cpu_affinity")
    if not isinstance(affinity, list) or any(not isinstance(cpu, int) or cpu < 0 for cpu in affinity):
        raise ValueError("latency report CPU affinity is invalid")
    if report["result"] != "PASS":
        if not isinstance(report.get("error"), str) or not report["error"]:
            raise ValueError("non-passing latency report requires an error")
        return
    for name in ("elapsed_ns", "process_cpu_ns", "throughput_fps"):
        if not isinstance(report.get(name), int) or isinstance(report[name], bool) or report[name] < 0:
            raise ValueError(f"passing latency report has invalid {name}")
    activity = report.get("load_activity")
    if not isinstance(activity, dict) or activity.get("kind") != report["load_profile"]:
        raise ValueError("passing latency report load activity is invalid")
    iterations = activity.get("iterations")
    if not isinstance(iterations, int) or isinstance(iterations, bool) or iterations < 0:
        raise ValueError("passing latency report load iterations are invalid")
    if report["load_profile"] == "idle" and iterations != 0:
        raise ValueError("idle latency report cannot contain load iterations")
    if report["load_profile"] == "status-readers" and iterations < 1:
        raise ValueError("status-reader latency report requires observed reads")
    if not MIN_SAMPLES <= report["sample_count"] <= MAX_SAMPLES:
        raise ValueError("passing latency report sample_count is outside the bounded range")
    if report.get("loss") or report.get("duplicates") or report.get("reordered"):
        raise ValueError("passing latency report cannot contain delivery anomalies")
    summary = report.get("latency")
    if not isinstance(summary, dict):
        raise ValueError("passing latency report requires a latency summary")
    for name in ("p50_ns", "p95_ns", "p99_ns", "max_ns", "jitter_ns", "missed_deadline_count"):
        if not isinstance(summary.get(name), int) or isinstance(summary[name], bool) or summary[name] < 0:
            raise ValueError(f"latency summary has invalid {name}")
    if not summary["p50_ns"] <= summary["p95_ns"] <= summary["p99_ns"] <= summary["max_ns"]:
        raise ValueError("latency percentiles must be monotonic")
    if summary.get("jitter_definition") != "population-standard-deviation-ns":
        raise ValueError("latency jitter definition is invalid")


def write_report(path: Path, report: dict[str, Any]) -> None:
    validate_report(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def measure(interface: str, warmup: int, sample_count: int, can_id: int, deadline_ns: int | None) -> list[int]:
    sender = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    receiver = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    sender.bind((interface,))
    receiver.bind((interface,))
    received: list[int] = []
    seen: set[int] = set()
    total = warmup + sample_count
    try:
        for sequence in range(total):
            started = time.monotonic_ns()
            sender.send(FRAME.pack(can_id, 8, sequence.to_bytes(8, "big")))
            if not select.select([receiver], [], [], 0.25)[0]:
                raise AssertionError(f"latency frame {sequence} was not received within 250 ms")
            frame_id, length, payload = FRAME.unpack(receiver.recv(FRAME.size))
            observed_sequence = int.from_bytes(payload, "big")
            if frame_id != can_id or length != 8 or observed_sequence != sequence or observed_sequence in seen:
                raise AssertionError(
                    f"unexpected latency frame: id={frame_id:#x} length={length} sequence={observed_sequence}"
                )
            seen.add(observed_sequence)
            observed = time.monotonic_ns() - started
            if observed < 0:
                raise AssertionError("monotonic clock regressed")
            if sequence >= warmup:
                received.append(observed)
        if len(seen) != total or len(received) != sample_count:
            raise AssertionError(f"latency run incomplete: received {len(received)}/{sample_count} measured frames")
        return received
    finally:
        sender.close()
        receiver.close()


def measure_profile(
    interface: str,
    warmup: int,
    sample_count: int,
    can_id: int,
    deadline_ns: int | None,
    load_profile: str,
    status_path: Path,
) -> tuple[list[int], dict[str, int | str], int, int]:
    stop = threading.Event()
    errors: list[Exception] = []
    iterations = 0

    def read_status() -> None:
        nonlocal iterations
        try:
            while not stop.is_set():
                text = status_path.read_text(encoding="ascii")
                if "state" not in text or "queue_stopped" not in text:
                    raise AssertionError("debugfs status snapshot is incomplete")
                iterations += 1
        except Exception as exc:  # noqa: BLE001 - preserve load worker failure as evidence.
            errors.append(exc)
            stop.set()

    worker: threading.Thread | None = None
    if load_profile == "status-readers":
        worker = threading.Thread(target=read_status, name="latency-status-reader", daemon=True)
        worker.start()
    started_wall = time.monotonic_ns()
    started_cpu = time.process_time_ns()
    try:
        samples = measure(interface, warmup, sample_count, can_id, deadline_ns)
    finally:
        elapsed_ns = time.monotonic_ns() - started_wall
        process_cpu_ns = time.process_time_ns() - started_cpu
        stop.set()
        if worker is not None:
            worker.join(timeout=1)
            if worker.is_alive():
                errors.append(AssertionError("status reader did not stop within one second"))
    if errors:
        raise ExceptionGroup("latency load worker failed", errors)
    return samples, {"kind": load_profile, "iterations": iterations}, elapsed_ns, process_cpu_ns


def base_report(args: argparse.Namespace) -> dict[str, Any]:
    try:
        affinity = sorted(os.sched_getaffinity(0))
    except AttributeError:
        affinity = list(range(os.cpu_count() or 1))
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "virtual-wbcan-userspace",
        "result": "NOT_EXECUTED",
        "interface": args.interface,
        "commit": args.commit,
        "kernel": platform.release(),
        "kernel_config_sha256": kernel_config_hash(),
        "preemption_model": preemption_model(),
        "cpu_count": os.cpu_count() or 1,
        "cpu_affinity": affinity,
        "load_profile": args.load_profile,
        "clock": "monotonic_ns",
        "warmup_count": args.warmup,
        "sample_count": args.samples,
        "message_size": 8,
        "can_id": args.can_id,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("interface", nargs="?", default="wbcan0")
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--can-id", type=lambda value: int(value, 0), default=0x760)
    parser.add_argument("--deadline-ns", type=int)
    parser.add_argument("--load-profile", choices=("idle", "status-readers"), default="idle")
    parser.add_argument("--status-path", type=Path)
    parser.add_argument("--commit", default=os.environ.get("GITHUB_SHA", "unknown"))
    parser.add_argument("--report", type=Path, default=Path("/tmp/wbcan-latency-report.json"))
    parser.add_argument("--validate-report", type=Path)
    args = parser.parse_args()
    if args.validate_report is not None:
        validate_report(json.loads(args.validate_report.read_text(encoding="utf-8")))
        print(f"wbcan latency report valid: {args.validate_report}")
        return 0
    if not 0 <= args.warmup <= MAX_SAMPLES:
        parser.error(f"--warmup must be between 0 and {MAX_SAMPLES}")
    if not MIN_SAMPLES <= args.samples <= MAX_SAMPLES:
        parser.error(f"--samples must be between {MIN_SAMPLES} and {MAX_SAMPLES}")
    if not 0 <= args.can_id <= 0x7FF:
        parser.error("--can-id must be a standard 11-bit CAN ID")
    if args.deadline_ns is not None and args.deadline_ns <= 0:
        parser.error("--deadline-ns must be positive")
    if args.load_profile == "status-readers" and args.status_path is None:
        parser.error("--status-path is required for status-readers")
    report = base_report(args)
    try:
        status_path = args.status_path or Path("/dev/null")
        samples, activity, elapsed_ns, process_cpu_ns = measure_profile(
            args.interface,
            args.warmup,
            args.samples,
            args.can_id,
            args.deadline_ns,
            args.load_profile,
            status_path,
        )
        report.update(
            {
                "result": "PASS",
                "loss": 0,
                "duplicates": 0,
                "reordered": 0,
                "elapsed_ns": elapsed_ns,
                "process_cpu_ns": process_cpu_ns,
                "throughput_fps": round(args.samples * 1_000_000_000 / elapsed_ns),
                "load_activity": activity,
                "latency": summarize(samples, args.deadline_ns),
            }
        )
    except Exception as exc:  # noqa: BLE001 - preserve failure as evidence.
        report.update({"result": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
    write_report(args.report, report)
    if report["result"] != "PASS":
        raise SystemExit(report["error"])
    print(f"wbcan latency evidence: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
