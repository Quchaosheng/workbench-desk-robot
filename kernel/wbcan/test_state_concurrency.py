#!/usr/bin/env python3
"""Bounded wbcan controller-state and queue concurrency probe."""

import argparse
import errno
import json
import platform
import queue
import select
import socket
import struct
import subprocess
import threading
import time
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from typing import Any

REPORT_SCHEMA_VERSION = "wbcan-stress-report-v1"
REQUIRED_STAGES = (
    "reconfiguration",
    "link_lifecycle",
    "stop_drain",
    "bus_off_restart",
    "restart_cancellation",
    "restart_stop_race",
    "queue_recovery",
    "stats_sampling",
    "cleanup",
)

FRAME = struct.Struct("=IB3x8s")
ALLOWED_STATES = {
    "error-active",
    "error-warning",
    "error-passive",
    "bus-off",
    "stopped",
    "sleeping",
}
ALLOWED_SEND_ERRORS = {
    errno.EAGAIN,
    errno.ENETDOWN,
    errno.ENETUNREACH,
    errno.ENOBUFS,
    errno.EBUSY,
}


class Probe:
    def __init__(self, interface: str, debugfs: Path) -> None:
        self.interface = interface
        self.debugfs = debugfs
        self.restart_delay = Path("/sys/module/wbcan/parameters/test_restart_delay_ms")
        self.stop_delay = Path("/sys/module/wbcan/parameters/test_stop_delay_ms")
        self.errors: queue.SimpleQueue[Exception] = queue.SimpleQueue()
        self.abort = threading.Event()

    def command(self, *arguments: str) -> None:
        subprocess.run(arguments, check=True, timeout=2, stdout=subprocess.DEVNULL)

    def arm(self, value: str) -> None:
        (self.debugfs / "inject").write_text(f"{value}\n", encoding="ascii")

    def status(self) -> dict[str, str]:
        fields = dict(
            line.split(maxsplit=1)
            for line in (self.debugfs / "status").read_text(encoding="ascii").splitlines()
            if line.strip()
        )
        current = fields.get("state", "").strip()
        if current not in ALLOWED_STATES:
            raise AssertionError(f"invalid controller state snapshot: {current!r}")
        if current in {"stopped", "bus-off", "sleeping"} and fields.get("queue_stopped") != "yes":
            raise AssertionError(f"terminal state has an awake TX queue: {current!r}")
        return fields

    def state(self) -> str:
        return self.status()["state"].strip()

    def counter(self, name: str) -> int:
        value = self.status().get(name)
        if value is None:
            raise AssertionError(f"missing status counter: {name}")
        return int(value)

    def netdev_stats(self) -> dict[str, int]:
        root = Path("/sys/class/net") / self.interface / "statistics"
        names = ("tx_packets", "tx_bytes", "tx_dropped", "rx_packets", "rx_bytes", "rx_dropped")
        return {name: int((root / name).read_text(encoding="ascii")) for name in names}

    def wait_for_state(self, expected: str, timeout: float = 1.0) -> None:
        deadline = time.monotonic() + timeout
        current = self.state()
        while current != expected and time.monotonic() < deadline:
            time.sleep(0.002)
            current = self.state()
        if current != expected:
            raise AssertionError(f"state did not become {expected!r}: {current!r}")

    def wait_for_counter(self, name: str, minimum: int, timeout: float = 1.0) -> None:
        deadline = time.monotonic() + timeout
        current = self.counter(name)
        while current < minimum and time.monotonic() < deadline:
            time.sleep(0.002)
            current = self.counter(name)
        if current < minimum:
            raise AssertionError(f"{name} did not reach {minimum}: {current}")

    def raw_socket(self) -> socket.socket:
        can_socket = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        can_socket.bind((self.interface,))
        return can_socket

    def send_frames(self, count: int, can_id: int) -> None:
        can_socket = self.raw_socket()
        try:
            for sequence in range(count):
                if self.abort.is_set():
                    return
                payload = sequence.to_bytes(4, "big") + b"\0" * 4
                try:
                    can_socket.send(FRAME.pack(can_id, 8, payload))
                except OSError as exc:
                    if exc.errno not in ALLOWED_SEND_ERRORS:
                        raise
                time.sleep(0.0005)
        finally:
            can_socket.close()

    def send_until_stopped(self, stop: threading.Event, can_id: int) -> None:
        can_socket = self.raw_socket()
        can_socket.setblocking(False)
        sequence = 0
        try:
            while not stop.is_set():
                payload = sequence.to_bytes(4, "big") + b"\0" * 4
                try:
                    can_socket.send(FRAME.pack(can_id, 8, payload))
                except OSError as exc:
                    if exc.errno not in ALLOWED_SEND_ERRORS:
                        raise
                sequence = (sequence + 1) & 0xFFFFFFFF
                time.sleep(0.0001)
        finally:
            can_socket.close()

    def assert_send_rejected(self, can_socket: socket.socket, can_id: int) -> None:
        try:
            can_socket.send(FRAME.pack(can_id, 1, b"X" + b"\0" * 7))
        except OSError as exc:
            if exc.errno not in ALLOWED_SEND_ERRORS:
                raise
        else:
            raise AssertionError("CAN send unexpectedly succeeded while the link was stopped")

    def read_status(self, count: int) -> None:
        for _ in range(count):
            if self.abort.is_set():
                return
            self.state()

    def rearm_faults(self, count: int) -> None:
        for _ in range(count):
            if self.abort.is_set():
                return
            self.arm("stuff-err 1")
            self.arm("none 0")

    def cycle_links(self, count: int) -> None:
        for _ in range(count):
            if self.abort.is_set():
                return
            self.command("ip", "link", "set", self.interface, "down")
            self.wait_for_state("stopped")
            self.command("ip", "link", "set", self.interface, "up")
            self.wait_for_state("error-active")

    def capture(self, operation: Callable[..., None], *arguments: object) -> None:
        try:
            operation(*arguments)
        except Exception as exc:  # noqa: BLE001 - propagate worker failure to the main probe.
            self.errors.put(exc)

    def finish_threads(self, *threads: threading.Thread) -> None:
        stuck = [thread for thread in threads if thread.is_alive()]
        for thread in stuck:
            thread.join(timeout=0.1)
        errors: list[Exception] = []
        while True:
            try:
                errors.append(self.errors.get_nowait())
            except queue.Empty:
                break
        still_stuck = [thread.name for thread in threads if thread.is_alive()]
        if still_stuck:
            errors.append(AssertionError(f"concurrent probe exceeded time bound: {still_stuck}"))
        if errors:
            raise ExceptionGroup("concurrent wbcan worker failures", errors)

    def run_threads(self, *threads: threading.Thread) -> None:
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + 5
        for thread in threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        failed = False
        try:
            self.finish_threads(*threads)
        except Exception:
            failed = True
            self.abort.set()
            for thread in threads:
                thread.join(timeout=0.2)
            raise
        finally:
            if not failed:
                self.abort.clear()

    def exercise_reconfiguration(self) -> None:
        self.run_threads(
            threading.Thread(target=self.capture, args=(self.send_frames, 400, 0x730), name="tx-rearm", daemon=True),
            threading.Thread(target=self.capture, args=(self.read_status, 600), name="status-rearm", daemon=True),
            threading.Thread(target=self.capture, args=(self.rearm_faults, 150), name="fault-rearm", daemon=True),
        )

    def exercise_link_lifecycle(self) -> None:
        self.arm("none 0")
        self.run_threads(
            threading.Thread(target=self.capture, args=(self.send_frames, 500, 0x731), name="tx-link", daemon=True),
            threading.Thread(target=self.capture, args=(self.read_status, 800), name="status-link", daemon=True),
            threading.Thread(target=self.capture, args=(self.cycle_links, 8), name="link-cycle", daemon=True),
        )

    def exercise_stop_drain(self) -> None:
        self.arm("none 0")
        before_tx = self.counter("tx_frames")
        stop = threading.Event()
        sender = threading.Thread(
            target=self.capture,
            args=(self.send_until_stopped, stop, 0x736),
            name="tx-stop-drain",
            daemon=True,
        )
        sender.start()
        failures: list[Exception] = []
        try:
            self.wait_for_counter("tx_frames", before_tx + 50)
            self.command("ip", "link", "set", self.interface, "down")
            self.wait_for_state("stopped")
            stopped_tx = self.counter("tx_frames")
            time.sleep(0.075)
            if self.counter("tx_frames") != stopped_tx:
                raise AssertionError("TX advanced after link stop returned")
        except Exception as exc:  # noqa: BLE001 - combine the cutover and worker failures.
            failures.append(exc)
        finally:
            stop.set()
            sender.join(timeout=2)

        try:
            self.finish_threads(sender)
        except Exception as exc:  # noqa: BLE001 - combine the cutover and worker failures.
            failures.append(exc)
        if failures:
            raise ExceptionGroup("link-stop drain failures", failures)
        self.command("ip", "link", "set", self.interface, "up")
        self.wait_for_state("error-active")

    def exercise_bus_off_restart(self) -> None:
        self.command("ip", "link", "set", self.interface, "down")
        self.command("ip", "link", "set", self.interface, "type", "can", "restart-ms", "50")
        self.command("ip", "link", "set", self.interface, "up")
        sender = self.raw_socket()
        try:
            for sequence in range(8):
                self.arm("bus-off 1")
                sender.send(FRAME.pack(0x732, 1, bytes([sequence]) + b"\0" * 7))
                self.wait_for_state("bus-off")
                self.wait_for_state("error-active", timeout=2)
        finally:
            sender.close()

    def exercise_restart_cancellation(self) -> None:
        self.command("ip", "link", "set", self.interface, "down")
        self.command("ip", "link", "set", self.interface, "type", "can", "restart-ms", "250")
        self.command("ip", "link", "set", self.interface, "up")
        sender = self.raw_socket()
        try:
            self.arm("bus-off 1")
            sender.send(FRAME.pack(0x732, 1, b"\xff" + b"\0" * 7))
            self.wait_for_state("bus-off")
        finally:
            sender.close()
        self.command("ip", "link", "set", self.interface, "down")
        stopped_tx = self.counter("tx_frames")
        time.sleep(0.35)
        self.wait_for_state("stopped")
        if self.counter("tx_frames") != stopped_tx:
            raise AssertionError("TX advanced after link stop returned")
        self.command("ip", "link", "set", self.interface, "up")

    def exercise_restart_stop_race(self) -> None:
        down: threading.Thread | None = None
        try:
            for sequence in range(4):
                self.command("ip", "link", "set", self.interface, "down")
                self.command("ip", "link", "set", self.interface, "type", "can", "restart-ms", "50")
                self.command("ip", "link", "set", self.interface, "up")
                before_restart = self.counter("restart_attempts")
                before_stop = self.counter("stop_attempts")
                # Hold stop on both sides of STOPPED publication. Restart
                # deterministically wins after the first drain, then status
                # observes the atomic STOPPED + queue-stopped commit before
                # close_candev() can perform the final defensive drain.
                self.restart_delay.write_text("100\n", encoding="ascii")
                self.stop_delay.write_text("250\n", encoding="ascii")
                sender = self.raw_socket()
                try:
                    self.arm("bus-off 1")
                    sender.send(FRAME.pack(0x734, 1, bytes([sequence]) + b"\0" * 7))
                    self.wait_for_state("bus-off")
                    down = threading.Thread(
                        target=self.capture,
                        args=(self.command, "ip", "link", "set", self.interface, "down"),
                        name="stop-during-restart",
                        daemon=True,
                    )
                    down.start()
                    self.wait_for_counter("stop_attempts", before_stop + 1)
                    self.wait_for_counter("restart_attempts", before_restart + 1)
                    deadline = time.monotonic() + 1
                    saw_active = False
                    saw_stopped = False
                    while down.is_alive() and time.monotonic() < deadline:
                        current = self.state()
                        saw_active |= current == "error-active"
                        saw_stopped |= current == "stopped"
                        time.sleep(0.002)
                    if not saw_active:
                        raise AssertionError("restart did not commit while stop was draining")
                    if not saw_stopped:
                        raise AssertionError("STOPPED publication was not observable before stop completed")
                    down.join(timeout=2)
                    self.finish_threads(down)
                    self.wait_for_state("stopped")
                    stopped_tx = self.counter("tx_frames")
                    self.assert_send_rejected(sender, 0x735)
                    time.sleep(0.075)
                    if self.state() != "stopped":
                        raise AssertionError("restart raced past link stop")
                    if self.counter("tx_frames") != stopped_tx:
                        raise AssertionError("TX advanced while restart raced with link stop")
                finally:
                    sender.close()

                # In the opposite ordering, restart has entered the
                # callback but stop publishes STOPPED before the callback
                # takes the TX lock. The BUS_OFF guard must reject the stale
                # restart after close_candev() waits for it.
                self.command("ip", "link", "set", self.interface, "up")
                self.restart_delay.write_text("300\n", encoding="ascii")
                self.stop_delay.write_text("0\n", encoding="ascii")
                before_restart = self.counter("restart_attempts")
                sender = self.raw_socket()
                try:
                    self.arm("bus-off 1")
                    sender.send(FRAME.pack(0x737, 1, bytes([sequence]) + b"\0" * 7))
                    self.wait_for_state("bus-off")
                    self.wait_for_counter("restart_attempts", before_restart + 1)
                finally:
                    sender.close()
                started = time.monotonic()
                self.command("ip", "link", "set", self.interface, "down")
                if time.monotonic() - started < 0.1:
                    raise AssertionError("link stop did not wait for entered restart callback")
                self.wait_for_state("stopped")
                time.sleep(0.075)
                if self.state() != "stopped":
                    raise AssertionError("stale restart overwrote STOPPED state")
        finally:
            if down is not None and down.is_alive():
                down.join(timeout=2)
            self.restart_delay.write_text("0\n", encoding="ascii")
            self.stop_delay.write_text("0\n", encoding="ascii")

        self.command("ip", "link", "set", self.interface, "up")

    def verify_queue_recovery(self) -> None:
        self.arm("none 0")
        sender = self.raw_socket()
        peer = self.raw_socket()
        try:
            sender.send(FRAME.pack(0x733, 2, b"OK" + b"\0" * 6))
            if not select.select([peer], [], [], 1)[0]:
                raise AssertionError("TX queue remained stopped after recovery")
            can_id, length, payload = FRAME.unpack(peer.recv(FRAME.size))
            if can_id != 0x733 or length != 2 or payload[:2] != b"OK":
                raise AssertionError("post-recovery frame was corrupted")
        finally:
            sender.close()
            peer.close()

    def exercise_stats_sampling(self) -> None:
        self.arm("none 0")
        stop = threading.Event()
        samples: list[dict[str, int]] = []

        def sample() -> None:
            while not stop.is_set():
                samples.append(self.netdev_stats())
                time.sleep(0.0005)

        sampler = threading.Thread(target=sample, name="stats-sampler", daemon=True)
        sender = threading.Thread(
            target=self.capture,
            args=(self.send_frames, 600, 0x739),
            name="stats-tx",
            daemon=True,
        )
        sampler.start()
        sender.start()
        sender.join(timeout=3)
        stop.set()
        sampler.join(timeout=1)
        self.finish_threads(sender, sampler)
        if len(samples) < 2:
            raise AssertionError("statistics sampler collected too few snapshots")
        for previous, current in pairwise(samples):
            for name in current:
                if current[name] < previous[name]:
                    raise AssertionError(f"netdev statistic regressed: {name}")


def validate_stress_report(report: object) -> None:
    if not isinstance(report, dict):
        raise ValueError("stress report must be a JSON object")
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise ValueError("stress report has an unsupported schema_version")
    if report.get("scope") != "virtual-wbcan-only":
        raise ValueError("stress report must retain the virtual-wbcan-only scope")
    if report.get("result") not in {"PASS", "FAIL"}:
        raise ValueError("stress report result must be PASS or FAIL")
    for name in ("interface", "kernel", "python", "started_at", "completed_at"):
        if not isinstance(report.get(name), str) or not report[name].strip():
            raise ValueError(f"stress report requires non-empty {name}")
    stages = report.get("stages")
    if not isinstance(stages, list):
        raise ValueError("stress report stages must be a list")
    stage_names: list[str] = []
    failed = False
    for stage in stages:
        if not isinstance(stage, dict):
            raise ValueError("stress report stage must be an object")
        name = stage.get("name")
        result = stage.get("result")
        duration_ms = stage.get("duration_ms")
        if not isinstance(name, str) or not name:
            raise ValueError("stress report stage requires a name")
        if result not in {"PASS", "FAIL"}:
            raise ValueError(f"stress report stage {name!r} has an invalid result")
        if not isinstance(duration_ms, int) or isinstance(duration_ms, bool) or duration_ms < 0:
            raise ValueError(f"stress report stage {name!r} has an invalid duration_ms")
        if result == "FAIL":
            failed = True
            if not isinstance(stage.get("error"), str) or not stage["error"]:
                raise ValueError(f"failed stress report stage {name!r} requires an error")
        stage_names.append(name)
    if len(stage_names) != len(set(stage_names)):
        raise ValueError("stress report contains duplicate stages")
    if report["result"] == "PASS" and (failed or tuple(stage_names) != REQUIRED_STAGES):
        raise ValueError("passing stress report must contain every required passing stage in order")
    if report["result"] == "FAIL" and not failed:
        raise ValueError("failed stress report must contain a failed stage")


def write_stress_report(path: Path, report: dict[str, Any]) -> None:
    validate_stress_report(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _stage(probe: Probe, name: str, operation: Callable[[], None], stages: list[dict[str, Any]]) -> None:
    started = time.monotonic()
    try:
        operation()
    except Exception as exc:
        stages.append(
            {
                "name": name,
                "result": "FAIL",
                "duration_ms": round((time.monotonic() - started) * 1000),
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        raise
    stages.append({"name": name, "result": "PASS", "duration_ms": round((time.monotonic() - started) * 1000)})


def run_probe(interface: str, debugfs: Path, report_path: Path | None) -> int:
    probe = Probe(interface, debugfs)
    started_at = time.time_ns()
    stages: list[dict[str, Any]] = []
    failure: Exception | None = None
    try:
        operations = (
            ("reconfiguration", probe.exercise_reconfiguration),
            ("link_lifecycle", probe.exercise_link_lifecycle),
            ("stop_drain", probe.exercise_stop_drain),
            ("bus_off_restart", probe.exercise_bus_off_restart),
            ("restart_cancellation", probe.exercise_restart_cancellation),
            ("restart_stop_race", probe.exercise_restart_stop_race),
            ("queue_recovery", probe.verify_queue_recovery),
            ("stats_sampling", probe.exercise_stats_sampling),
        )
        for name, operation in operations:
            _stage(probe, name, operation, stages)
    except Exception as exc:  # noqa: BLE001 - preserve the probe failure through cleanup.
        failure = exc
    finally:
        cleanup_started = time.monotonic()
        try:
            probe.restart_delay.write_text("0\n", encoding="ascii")
            probe.stop_delay.write_text("0\n", encoding="ascii")
            probe.arm("none 0")
            probe.command("ip", "link", "set", probe.interface, "down")
            probe.command("ip", "link", "set", probe.interface, "type", "can", "restart-ms", "100")
            probe.command("ip", "link", "set", probe.interface, "up")
        except Exception as exc:  # noqa: BLE001 - report probe and cleanup failures together.
            stages.append(
                {
                    "name": "cleanup",
                    "result": "FAIL",
                    "duration_ms": round((time.monotonic() - cleanup_started) * 1000),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            if failure is None:
                failure = exc
            else:
                failure = ExceptionGroup("probe and cleanup failures", [failure, exc])
        else:
            stages.append(
                {"name": "cleanup", "result": "PASS", "duration_ms": round((time.monotonic() - cleanup_started) * 1000)}
            )
    if report_path is not None:
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "scope": "virtual-wbcan-only",
            "result": "FAIL" if failure is not None else "PASS",
            "interface": interface,
            "kernel": platform.release(),
            "python": platform.python_version(),
            "started_at": str(started_at),
            "completed_at": str(time.time_ns()),
            "stages": stages,
        }
        write_stress_report(report_path, report)
    if failure is not None:
        raise failure
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("interface", nargs="?")
    parser.add_argument("debugfs", nargs="?", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--validate-report", type=Path)
    args = parser.parse_args()
    if args.validate_report is not None:
        if args.interface is not None or args.debugfs is not None or args.report is not None:
            parser.error("--validate-report cannot be combined with probe arguments")
        validate_stress_report(json.loads(args.validate_report.read_text(encoding="utf-8")))
        print(f"wbcan stress report valid: {args.validate_report}")
        return 0
    if args.interface is None or args.debugfs is None:
        parser.error("INTERFACE and DEBUGFS_DIRECTORY are required")
    return run_probe(args.interface, args.debugfs, args.report)


if __name__ == "__main__":
    raise SystemExit(main())
