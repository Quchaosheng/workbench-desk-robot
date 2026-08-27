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
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

FRAME = struct.Struct("=IB3x8s")
SCHEMA_VERSION = "wbcan-latency-report-v3"
MIN_SAMPLES = 10
MAX_SAMPLES = 100_000
MIN_REPETITIONS = 1
MAX_REPETITIONS = 20
MAX_LOAD_WORKERS = 32
WORKER_READY_TIMEOUT_S = 2.0
WORKER_JOIN_TIMEOUT_S = 2.0
CPU_WORK_BYTES = 64 * 1024
IO_WORK_BYTES = 4 * 1024
CPU_OPERATION = f"sha256-{CPU_WORK_BYTES}-bytes"
IO_OPERATION = f"pwrite-offset-zero-fsync-fstat-{IO_WORK_BYTES}-bytes"
LOAD_PROFILES = frozenset({"idle", "status-readers", "controlled-load"})
COMMON_REPORT_FIELDS = frozenset(
    {
        "schema_version",
        "scope",
        "result",
        "interface",
        "commit",
        "kernel",
        "kernel_config_sha256",
        "preemption_model",
        "cpu_count",
        "cpu_affinity",
        "load_profile",
        "load_configuration",
        "clock",
        "warmup_count",
        "sample_count",
        "message_size",
        "can_id",
        "deadline_ns",
        "repetition_count",
        "completed_repetitions",
        "run_budget",
        "runs",
    }
)


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


def _envelope(values: list[int]) -> dict[str, int]:
    return {
        "minimum": min(values),
        "nearest_rank_median": percentile(values, 50),
        "maximum": max(values),
    }


def aggregate_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    if not runs:
        raise ValueError("cannot aggregate an empty latency run list")
    latency_fields = ("p50_ns", "p95_ns", "p99_ns", "max_ns", "jitter_ns")
    return {
        "method": "per-run-min-nearest-rank-median-max",
        "run_count": len(runs),
        "elapsed_ns": _envelope([run["elapsed_ns"] for run in runs]),
        "process_cpu_ns": _envelope([run["process_cpu_ns"] for run in runs]),
        "throughput_fps": _envelope([run["throughput_fps"] for run in runs]),
        "latency": {field: _envelope([run["latency"][field] for run in runs]) for field in latency_fields},
        "total_missed_deadline_count": sum(run["latency"]["missed_deadline_count"] for run in runs),
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


def commit_identity() -> str:
    configured = os.environ.get("GITHUB_SHA")
    if configured:
        return configured
    try:
        result = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parents[2]), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return "unavailable"
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and commit else "unavailable"


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object_without_duplicates)


def _require_non_negative_integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"latency report has invalid {field}")
    return value


def _require_exact_keys(value: dict[str, Any], expected: set[str] | frozenset[str], field: str) -> None:
    if set(value) != set(expected):
        raise ValueError(f"{field} fields are invalid")


def _validate_load_configuration(report: dict[str, Any]) -> None:
    profile = report["load_profile"]
    configuration = report.get("load_configuration")
    if not isinstance(configuration, dict) or configuration.get("kind") != profile:
        raise ValueError("latency report load configuration is invalid")
    if profile == "idle":
        _require_exact_keys(configuration, {"kind"}, "idle latency configuration")
    elif profile == "status-readers":
        _require_exact_keys(configuration, {"kind", "status_path"}, "status-reader latency configuration")
        if not isinstance(configuration.get("status_path"), str) or not configuration["status_path"]:
            raise ValueError("status-reader latency configuration requires a path")
    else:
        _require_exact_keys(
            configuration,
            {
                "kind",
                "cpu_workers",
                "io_workers",
                "cpu_operation",
                "io_operation",
                "io_file_size_bytes",
                "load_directory",
            },
            "controlled latency configuration",
        )
        cpu_workers = _require_non_negative_integer(configuration.get("cpu_workers"), "CPU load worker count")
        io_workers = _require_non_negative_integer(configuration.get("io_workers"), "I/O load worker count")
        if cpu_workers < 1 or io_workers < 1 or cpu_workers + io_workers > MAX_LOAD_WORKERS:
            raise ValueError("controlled latency configuration has an invalid worker budget")
        if configuration.get("cpu_operation") != CPU_OPERATION or configuration.get("io_operation") != IO_OPERATION:
            raise ValueError("controlled latency configuration has an unknown operation")
        if configuration.get("io_file_size_bytes") != IO_WORK_BYTES:
            raise ValueError("controlled latency configuration has an invalid fixed I/O size")
        if not isinstance(configuration.get("load_directory"), str) or not configuration["load_directory"]:
            raise ValueError("controlled latency configuration requires a load directory")


def _validate_worker_activity(activity: object, *, worker_count: int, operation: str, field: str) -> int:
    if not isinstance(activity, dict):
        raise ValueError(f"controlled latency report requires {field} activity")
    expected = {"worker_count", "operation", "iterations", "worker_iterations"}
    if field == "I/O":
        expected.update({"bytes_written", "maximum_file_size_bytes"})
    _require_exact_keys(activity, expected, f"controlled latency {field} activity")
    if activity.get("worker_count") != worker_count or activity.get("operation") != operation:
        raise ValueError(f"controlled latency report has invalid {field} activity configuration")
    worker_iterations = activity.get("worker_iterations")
    if (
        not isinstance(worker_iterations, list)
        or len(worker_iterations) != worker_count
        or any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in worker_iterations)
    ):
        raise ValueError(f"controlled latency report requires observed activity from every {field} worker")
    iterations = _require_non_negative_integer(activity.get("iterations"), f"{field} iterations")
    if iterations != sum(worker_iterations):
        raise ValueError(f"controlled latency report {field} iteration total is inconsistent")
    return iterations


def _validate_load_activity(report: dict[str, Any], activity: object) -> None:
    profile = report["load_profile"]
    if not isinstance(activity, dict) or activity.get("kind") != profile:
        raise ValueError("passing latency report load activity is invalid")
    iterations = _require_non_negative_integer(activity.get("iterations"), "load iterations")
    if profile == "idle":
        _require_exact_keys(activity, {"kind", "iterations"}, "idle latency activity")
        if iterations != 0:
            raise ValueError("idle latency report cannot contain load activity")
        return
    if profile == "status-readers":
        _require_exact_keys(activity, {"kind", "iterations"}, "status-reader latency activity")
        if iterations < 1:
            raise ValueError("status-reader latency report requires observed reads")
        return

    _require_exact_keys(activity, {"kind", "iterations", "cpu", "io"}, "controlled latency activity")

    configuration = report["load_configuration"]
    cpu_iterations = _validate_worker_activity(
        activity.get("cpu"),
        worker_count=configuration["cpu_workers"],
        operation=CPU_OPERATION,
        field="CPU",
    )
    io_iterations = _validate_worker_activity(
        activity.get("io"),
        worker_count=configuration["io_workers"],
        operation=IO_OPERATION,
        field="I/O",
    )
    io_activity = activity["io"]
    if io_activity.get("bytes_written") != io_iterations * IO_WORK_BYTES:
        raise ValueError("controlled latency report I/O byte total is inconsistent")
    if io_activity.get("maximum_file_size_bytes") != IO_WORK_BYTES:
        raise ValueError("controlled latency report must use fixed-size I/O files")
    if iterations != cpu_iterations + io_iterations:
        raise ValueError("controlled latency report load iteration total is inconsistent")


def _validate_latency_summary(summary: object, *, sample_count: int, deadline_ns: int | None) -> None:
    if not isinstance(summary, dict):
        raise ValueError("passing latency report requires a latency summary")
    _require_exact_keys(
        summary,
        {
            "p50_ns",
            "p95_ns",
            "p99_ns",
            "max_ns",
            "jitter_definition",
            "jitter_ns",
            "deadline_ns",
            "missed_deadline_count",
        },
        "latency summary",
    )
    for name in ("p50_ns", "p95_ns", "p99_ns", "max_ns", "jitter_ns", "missed_deadline_count"):
        _require_non_negative_integer(summary.get(name), name)
    if not summary["p50_ns"] <= summary["p95_ns"] <= summary["p99_ns"] <= summary["max_ns"]:
        raise ValueError("latency percentiles must be monotonic")
    if summary.get("jitter_definition") != "population-standard-deviation-ns":
        raise ValueError("latency jitter definition is invalid")
    if summary.get("deadline_ns") != deadline_ns:
        raise ValueError("latency deadline does not match the run configuration")
    if summary["missed_deadline_count"] > sample_count:
        raise ValueError("latency missed-deadline count exceeds the sample count")


def _validate_run(report: dict[str, Any], run: object, expected_index: int) -> None:
    if not isinstance(run, dict) or run.get("run_index") != expected_index:
        raise ValueError("latency report run ordering is invalid")
    _require_exact_keys(
        run,
        {
            "run_index",
            "elapsed_ns",
            "process_cpu_ns",
            "throughput_fps",
            "load_activity",
            "loss",
            "duplicates",
            "reordered",
            "latency",
        },
        "latency run",
    )
    elapsed_ns = _require_non_negative_integer(run.get("elapsed_ns"), "elapsed_ns")
    if elapsed_ns == 0:
        raise ValueError("latency report elapsed_ns must be positive")
    _require_non_negative_integer(run.get("process_cpu_ns"), "process_cpu_ns")
    _require_non_negative_integer(run.get("throughput_fps"), "throughput_fps")
    for field in ("loss", "duplicates", "reordered"):
        if _require_non_negative_integer(run.get(field), field) != 0:
            raise ValueError("passing latency report cannot contain delivery anomalies")
    _validate_load_activity(report, run.get("load_activity"))
    _validate_latency_summary(
        run.get("latency"), sample_count=report["sample_count"], deadline_ns=report["deadline_ns"]
    )


def validate_report(report: object) -> None:
    if not isinstance(report, dict):
        raise ValueError("latency report must be an object")
    if report.get("schema_version") != SCHEMA_VERSION or report.get("scope") != "virtual-wbcan-userspace":
        raise ValueError("latency report schema or scope is invalid")
    if report.get("result") not in {"PASS", "FAIL", "NOT_EXECUTED"}:
        raise ValueError("latency report result is invalid")
    expected_fields = COMMON_REPORT_FIELDS | ({"observed_envelope"} if report["result"] == "PASS" else {"error"})
    _require_exact_keys(report, expected_fields, "latency report")
    for name in ("interface", "commit", "kernel", "kernel_config_sha256", "preemption_model", "clock"):
        if not isinstance(report.get(name), str) or not report[name]:
            raise ValueError(f"latency report requires {name}")
    if report.get("clock") != "monotonic_ns":
        raise ValueError("latency report clock must be monotonic_ns")
    if report.get("load_profile") not in LOAD_PROFILES:
        raise ValueError("latency report load_profile is invalid")
    for name in ("cpu_count", "warmup_count", "sample_count", "message_size", "can_id"):
        _require_non_negative_integer(report.get(name), name)
    if report["cpu_count"] < 1 or report["message_size"] != 8 or report["can_id"] > 0x7FF:
        raise ValueError("latency report runtime or CAN configuration is invalid")
    if not 0 <= report["warmup_count"] <= MAX_SAMPLES:
        raise ValueError("latency report warm-up count is outside the bounded range")
    if not MIN_SAMPLES <= report["sample_count"] <= MAX_SAMPLES:
        raise ValueError("latency report sample_count is outside the bounded range")
    deadline_ns = report.get("deadline_ns")
    if deadline_ns is not None and (
        not isinstance(deadline_ns, int) or isinstance(deadline_ns, bool) or deadline_ns <= 0
    ):
        raise ValueError("latency report deadline_ns is invalid")
    affinity = report.get("cpu_affinity")
    if (
        not isinstance(affinity, list)
        or not affinity
        or any(not isinstance(cpu, int) or isinstance(cpu, bool) or cpu < 0 for cpu in affinity)
        or len(set(affinity)) != len(affinity)
        or affinity != sorted(affinity)
    ):
        raise ValueError("latency report CPU affinity is invalid")
    repetitions = _require_non_negative_integer(report.get("repetition_count"), "repetition_count")
    completed = _require_non_negative_integer(report.get("completed_repetitions"), "completed_repetitions")
    if not MIN_REPETITIONS <= repetitions <= MAX_REPETITIONS or completed > repetitions:
        raise ValueError("latency report repetition count is outside the bounded range")
    budget = report.get("run_budget")
    expected_budget = {
        "maximum_repetitions": MAX_REPETITIONS,
        "maximum_samples_per_run": MAX_SAMPLES,
        "requested_repetitions": repetitions,
        "warmup_frames_per_run": report["warmup_count"],
        "measured_frames_per_run": report["sample_count"],
        "total_frame_attempts": repetitions * (report["warmup_count"] + report["sample_count"]),
    }
    if budget != expected_budget:
        raise ValueError("latency report run budget is inconsistent")
    _validate_load_configuration(report)
    runs = report.get("runs")
    if not isinstance(runs, list) or len(runs) != completed:
        raise ValueError("latency report completed run list is inconsistent")
    for index, run in enumerate(runs, start=1):
        _validate_run(report, run, index)
    if report["result"] != "PASS":
        if not isinstance(report.get("error"), str) or not report["error"]:
            raise ValueError("non-passing latency report requires an error")
        if report["result"] == "NOT_EXECUTED" and (completed != 0 or runs):
            raise ValueError("NOT_EXECUTED latency evidence cannot contain completed runs")
        return
    if completed != repetitions:
        raise ValueError("passing latency report did not complete its repetition budget")
    if report.get("observed_envelope") != aggregate_runs(runs):
        raise ValueError("latency report observed envelope is inconsistent")


def serialized_report(report: dict[str, Any]) -> bytes:
    validate_report(report)
    return (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()


def write_report(path: Path, report: dict[str, Any]) -> None:
    payload = serialized_report(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def measure(interface: str, warmup: int, sample_count: int, can_id: int) -> list[int]:
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


def _record_worker_error(
    errors: list[Exception], error_lock: threading.Lock, stop: threading.Event, error: Exception
) -> None:
    with error_lock:
        errors.append(error)
    stop.set()


def _cpu_load_worker(
    stop: threading.Event,
    ready: threading.Event,
    counts: list[int],
    index: int,
    errors: list[Exception],
    error_lock: threading.Lock,
) -> None:
    iterations = 0
    payload = bytes([index % 251]) * CPU_WORK_BYTES
    try:
        while not stop.is_set():
            hashlib.sha256(payload).digest()
            iterations += 1
            if iterations == 1:
                ready.set()
    except Exception as exc:  # noqa: BLE001 - worker failures are preserved as evidence.
        _record_worker_error(errors, error_lock, stop, exc)
    finally:
        counts[index] = iterations


def _io_load_worker(
    path: Path,
    stop: threading.Event,
    ready: threading.Event,
    counts: list[int],
    maximum_file_sizes: list[int],
    index: int,
    errors: list[Exception],
    error_lock: threading.Lock,
) -> None:
    iterations = 0
    maximum_file_size = 0
    descriptor = -1
    payload = bytes([(index + 1) % 251]) * IO_WORK_BYTES
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_TRUNC, 0o600)
        while not stop.is_set():
            written = os.pwrite(descriptor, payload, 0)
            if written != IO_WORK_BYTES:
                raise OSError(f"controlled I/O worker short write: {written}/{IO_WORK_BYTES}")
            os.fsync(descriptor)
            maximum_file_size = max(maximum_file_size, os.fstat(descriptor).st_size)
            iterations += 1
            if iterations == 1:
                ready.set()
    except Exception as exc:  # noqa: BLE001 - worker failures are preserved as evidence.
        _record_worker_error(errors, error_lock, stop, exc)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        counts[index] = iterations
        maximum_file_sizes[index] = maximum_file_size


def measure_profile(
    interface: str,
    warmup: int,
    sample_count: int,
    can_id: int,
    load_profile: str,
    status_path: Path | None,
    cpu_load_workers: int,
    io_load_workers: int,
    load_directory: Path,
) -> tuple[list[int], dict[str, Any], int, int]:
    stop = threading.Event()
    errors: list[Exception] = []
    error_lock = threading.Lock()
    workers: list[threading.Thread] = []
    ready_events: list[threading.Event] = []
    status_iterations = [0]
    cpu_iterations = [0] * cpu_load_workers
    io_iterations = [0] * io_load_workers
    io_maximum_file_sizes = [0] * io_load_workers
    temporary_directory: tempfile.TemporaryDirectory[str] | None = None

    def read_status(ready: threading.Event) -> None:
        iterations = 0
        try:
            if status_path is None:
                raise AssertionError("status-reader profile has no debugfs status path")
            while not stop.is_set():
                text = status_path.read_text(encoding="ascii")
                if "state" not in text or "queue_stopped" not in text:
                    raise AssertionError("debugfs status snapshot is incomplete")
                iterations += 1
                if iterations == 1:
                    ready.set()
        except Exception as exc:  # noqa: BLE001 - worker failures are preserved as evidence.
            _record_worker_error(errors, error_lock, stop, exc)
        finally:
            status_iterations[0] = iterations

    if load_profile == "status-readers":
        ready = threading.Event()
        ready_events.append(ready)
        workers.append(threading.Thread(target=read_status, args=(ready,), name="latency-status-reader", daemon=True))
    elif load_profile == "controlled-load":
        temporary_directory = tempfile.TemporaryDirectory(prefix="wbcan-latency-", dir=load_directory)
        work_path = Path(temporary_directory.name)
        for index in range(cpu_load_workers):
            ready = threading.Event()
            ready_events.append(ready)
            workers.append(
                threading.Thread(
                    target=_cpu_load_worker,
                    args=(stop, ready, cpu_iterations, index, errors, error_lock),
                    name=f"latency-cpu-load-{index}",
                    daemon=True,
                )
            )
        for index in range(io_load_workers):
            ready = threading.Event()
            ready_events.append(ready)
            workers.append(
                threading.Thread(
                    target=_io_load_worker,
                    args=(
                        work_path / f"io-{index}.bin",
                        stop,
                        ready,
                        io_iterations,
                        io_maximum_file_sizes,
                        index,
                        errors,
                        error_lock,
                    ),
                    name=f"latency-io-load-{index}",
                    daemon=True,
                )
            )

    for worker in workers:
        worker.start()
    started_wall = time.monotonic_ns()
    started_cpu = time.process_time_ns()
    samples: list[int] | None = None
    try:
        ready_deadline = time.monotonic() + WORKER_READY_TIMEOUT_S
        for ready in ready_events:
            if not ready.wait(max(0.0, ready_deadline - time.monotonic())):
                raise TimeoutError("latency load worker did not become active within two seconds")
        with error_lock:
            worker_failed = bool(errors)
        if not worker_failed:
            samples = measure(interface, warmup, sample_count, can_id)
    except Exception as exc:  # noqa: BLE001 - preserve measurement and worker failures together.
        with error_lock:
            errors.append(exc)
    finally:
        elapsed_ns = time.monotonic_ns() - started_wall
        process_cpu_ns = time.process_time_ns() - started_cpu
        stop.set()
        join_deadline = time.monotonic() + WORKER_JOIN_TIMEOUT_S
        for worker in workers:
            worker.join(timeout=max(0.0, join_deadline - time.monotonic()))
            if worker.is_alive():
                with error_lock:
                    errors.append(TimeoutError(f"{worker.name} did not stop within two seconds"))
        if temporary_directory is not None:
            temporary_directory.cleanup()
    if errors:
        details = "; ".join(f"{type(error).__name__}: {error}" for error in errors)
        raise RuntimeError(f"latency profile failed: {details}")
    if samples is None:
        raise AssertionError("latency profile produced no samples")

    if load_profile == "idle":
        activity: dict[str, Any] = {"kind": "idle", "iterations": 0}
    elif load_profile == "status-readers":
        activity = {"kind": "status-readers", "iterations": status_iterations[0]}
    else:
        cpu_total = sum(cpu_iterations)
        io_total = sum(io_iterations)
        activity = {
            "kind": "controlled-load",
            "iterations": cpu_total + io_total,
            "cpu": {
                "worker_count": cpu_load_workers,
                "operation": CPU_OPERATION,
                "iterations": cpu_total,
                "worker_iterations": cpu_iterations,
            },
            "io": {
                "worker_count": io_load_workers,
                "operation": IO_OPERATION,
                "iterations": io_total,
                "worker_iterations": io_iterations,
                "bytes_written": io_total * IO_WORK_BYTES,
                "maximum_file_size_bytes": max(io_maximum_file_sizes),
            },
        }
    return samples, activity, elapsed_ns, process_cpu_ns


def _load_configuration(args: argparse.Namespace) -> dict[str, Any]:
    if args.load_profile == "idle":
        return {"kind": "idle"}
    if args.load_profile == "status-readers":
        return {"kind": "status-readers", "status_path": str(args.status_path)}
    return {
        "kind": "controlled-load",
        "cpu_workers": args.cpu_load_workers,
        "io_workers": args.io_load_workers,
        "cpu_operation": CPU_OPERATION,
        "io_operation": IO_OPERATION,
        "io_file_size_bytes": IO_WORK_BYTES,
        "load_directory": str(args.load_directory),
    }


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
        "load_configuration": _load_configuration(args),
        "clock": "monotonic_ns",
        "warmup_count": args.warmup,
        "sample_count": args.samples,
        "message_size": 8,
        "can_id": args.can_id,
        "deadline_ns": args.deadline_ns,
        "repetition_count": args.repetitions,
        "completed_repetitions": 0,
        "run_budget": {
            "maximum_repetitions": MAX_REPETITIONS,
            "maximum_samples_per_run": MAX_SAMPLES,
            "requested_repetitions": args.repetitions,
            "warmup_frames_per_run": args.warmup,
            "measured_frames_per_run": args.samples,
            "total_frame_attempts": args.repetitions * (args.warmup + args.samples),
        },
        "runs": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("interface", nargs="?", default="wbcan0")
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--can-id", type=lambda value: int(value, 0), default=0x760)
    parser.add_argument("--deadline-ns", type=int)
    parser.add_argument("--load-profile", choices=sorted(LOAD_PROFILES), default="idle")
    parser.add_argument("--status-path", type=Path)
    parser.add_argument("--cpu-load-workers", type=int)
    parser.add_argument("--io-load-workers", type=int)
    parser.add_argument("--load-directory", type=Path, default=Path("/tmp"))
    parser.add_argument("--commit")
    parser.add_argument("--report", type=Path, default=Path("/tmp/wbcan-latency-report.json"))
    parser.add_argument("--validate-report", type=Path)
    args = parser.parse_args()
    if args.validate_report is not None:
        validate_report(load_json(args.validate_report))
        print(f"wbcan latency report valid: {args.validate_report}")
        return 0
    args.commit = args.commit or commit_identity()
    if not 0 <= args.warmup <= MAX_SAMPLES:
        parser.error(f"--warmup must be between 0 and {MAX_SAMPLES}")
    if not MIN_SAMPLES <= args.samples <= MAX_SAMPLES:
        parser.error(f"--samples must be between {MIN_SAMPLES} and {MAX_SAMPLES}")
    if not MIN_REPETITIONS <= args.repetitions <= MAX_REPETITIONS:
        parser.error(f"--repetitions must be between {MIN_REPETITIONS} and {MAX_REPETITIONS}")
    if not 0 <= args.can_id <= 0x7FF:
        parser.error("--can-id must be a standard 11-bit CAN ID")
    if args.deadline_ns is not None and args.deadline_ns <= 0:
        parser.error("--deadline-ns must be positive")
    if args.load_profile == "status-readers" and args.status_path is None:
        parser.error("--status-path is required for status-readers")
    if args.load_profile != "status-readers" and args.status_path is not None:
        parser.error("--status-path is only valid for status-readers")
    if args.load_profile == "controlled-load":
        args.cpu_load_workers = 1 if args.cpu_load_workers is None else args.cpu_load_workers
        args.io_load_workers = 1 if args.io_load_workers is None else args.io_load_workers
        if (
            args.cpu_load_workers < 1
            or args.io_load_workers < 1
            or args.cpu_load_workers + args.io_load_workers > MAX_LOAD_WORKERS
        ):
            parser.error(
                f"controlled load requires at least one CPU and I/O worker and at most {MAX_LOAD_WORKERS} total"
            )
        if not args.load_directory.is_dir():
            parser.error("--load-directory must be an existing directory")
    else:
        if args.cpu_load_workers is not None or args.io_load_workers is not None:
            parser.error("load worker counts are only valid for controlled-load")
        args.cpu_load_workers = 0
        args.io_load_workers = 0

    report = base_report(args)
    runs: list[dict[str, Any]] = []
    try:
        for run_index in range(1, args.repetitions + 1):
            samples, activity, elapsed_ns, process_cpu_ns = measure_profile(
                args.interface,
                args.warmup,
                args.samples,
                args.can_id,
                args.load_profile,
                args.status_path,
                args.cpu_load_workers,
                args.io_load_workers,
                args.load_directory,
            )
            runs.append(
                {
                    "run_index": run_index,
                    "elapsed_ns": elapsed_ns,
                    "process_cpu_ns": process_cpu_ns,
                    "throughput_fps": round(args.samples * 1_000_000_000 / elapsed_ns),
                    "load_activity": activity,
                    "loss": 0,
                    "duplicates": 0,
                    "reordered": 0,
                    "latency": summarize(samples, args.deadline_ns),
                }
            )
            report.update({"completed_repetitions": len(runs), "runs": runs})
        report.update({"result": "PASS", "observed_envelope": aggregate_runs(runs)})
    except Exception as exc:  # noqa: BLE001 - preserve failure as evidence.
        report.update(
            {
                "result": "FAIL",
                "completed_repetitions": len(runs),
                "runs": runs,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    write_report(args.report, report)
    if report["result"] != "PASS":
        raise SystemExit(report["error"])
    print(f"wbcan latency evidence: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
