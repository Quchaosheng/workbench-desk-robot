import importlib.util
import json
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DRIVER_PATH = ROOT / "kernel" / "wbcan" / "wbcan.c"
MODULE_PATH = ROOT / "kernel" / "wbcan" / "validate_test_report.py"
TEST_SCRIPT = ROOT / "kernel" / "wbcan" / "test_wbcan.sh"
STRESS_PATH = ROOT / "kernel" / "wbcan" / "test_state_concurrency.py"
STRESS_MAKEFILE = ROOT / "kernel" / "wbcan" / "Makefile"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
LATENCY_PATH = ROOT / "kernel" / "wbcan" / "test_latency.py"
LATENCY_CAMPAIGN_PATH = ROOT / "kernel" / "wbcan" / "validate_latency_campaign.py"
DIAGNOSTICS_PATH = ROOT / "kernel" / "wbcan" / "validate_kernel_diagnostics.py"
SPEC = importlib.util.spec_from_file_location("validate_wbcan_report", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
STRESS_SPEC = importlib.util.spec_from_file_location("wbcan_stress", STRESS_PATH)
assert STRESS_SPEC and STRESS_SPEC.loader
STRESS = importlib.util.module_from_spec(STRESS_SPEC)
STRESS_SPEC.loader.exec_module(STRESS)
LATENCY_SPEC = importlib.util.spec_from_file_location("test_latency", LATENCY_PATH)
assert LATENCY_SPEC and LATENCY_SPEC.loader
LATENCY = importlib.util.module_from_spec(LATENCY_SPEC)
sys.path.insert(0, str(LATENCY_PATH.parent))
sys.modules[LATENCY_SPEC.name] = LATENCY
LATENCY_SPEC.loader.exec_module(LATENCY)
LATENCY_CAMPAIGN_SPEC = importlib.util.spec_from_file_location("wbcan_latency_campaign", LATENCY_CAMPAIGN_PATH)
assert LATENCY_CAMPAIGN_SPEC and LATENCY_CAMPAIGN_SPEC.loader
LATENCY_CAMPAIGN = importlib.util.module_from_spec(LATENCY_CAMPAIGN_SPEC)
LATENCY_CAMPAIGN_SPEC.loader.exec_module(LATENCY_CAMPAIGN)
DIAGNOSTICS_SPEC = importlib.util.spec_from_file_location("wbcan_diagnostics", DIAGNOSTICS_PATH)
assert DIAGNOSTICS_SPEC and DIAGNOSTICS_SPEC.loader
DIAGNOSTICS = importlib.util.module_from_spec(DIAGNOSTICS_SPEC)
DIAGNOSTICS_SPEC.loader.exec_module(DIAGNOSTICS)


HEADER = "result\ttest_id\tname\texpected\tactual\n"


def _ready_then_sleeping_latency_worker(_stop: object, _start: object, ready: object, *_args: object) -> None:
    """Become ready, then keep a worker alive long enough to force cleanup."""

    ready.set()
    time.sleep(10)


def _nonzero_latency_worker(*_args: object) -> None:
    """Exit abnormally so cleanup must reject the worker's exit status."""

    raise SystemExit(7)


def _delayed_ready_cpu_worker(
    stop: object,
    start: object,
    ready: object,
    counts: object,
    cpu_times: object,
    index: int,
    error_connection: object,
) -> None:
    """Delay setup so the parent timing window can be tested independently."""

    time.sleep(0.2)
    ready.set()
    try:
        if not start.wait(1):
            return
        while not stop.is_set():
            counts[index] = 1
            cpu_times[index] = 1
            time.sleep(0.005)
    finally:
        error_connection.close()


def _write_report(path: Path, rows: list[str]) -> None:
    path.write_text(HEADER + "".join(rows), encoding="utf-8")


def test_report_accepts_unique_passing_checks(tmp_path: Path) -> None:
    report = tmp_path / "report.tsv"
    checks = MODULE.expected_checks()
    _write_report(report, [f"PASS\t{test_id}\t{name}\t1\t1\n" for test_id, name in checks.items()])

    assert MODULE.validate_report(report, minimum_checks=2) == len(checks)


def test_report_rejects_duplicate_ids(tmp_path: Path) -> None:
    report = tmp_path / "report.tsv"
    _write_report(
        report,
        [
            "PASS\twbcan-first\tfirst\t1\t1\n",
            "PASS\twbcan-first\tfirst\t1\t1\n",
        ],
    )

    with pytest.raises(MODULE.ReportError, match="duplicate test_id"):
        MODULE.validate_report(report, minimum_checks=1, required_test_ids={"wbcan-first"})


def test_report_rejects_failed_checks(tmp_path: Path) -> None:
    report = tmp_path / "report.tsv"
    _write_report(report, ["FAIL\twbcan-broken\tbroken\t1\t0\n"])

    with pytest.raises(MODULE.ReportError, match="failed checks"):
        MODULE.validate_report(report, minimum_checks=1, required_test_ids={"wbcan-broken"})


def test_report_requires_the_expected_check_count(tmp_path: Path) -> None:
    report = tmp_path / "report.tsv"
    _write_report(report, ["PASS\twbcan-only_check\tonly check\t1\t1\n"])

    with pytest.raises(MODULE.ReportError, match="at least 2 checks"):
        MODULE.validate_report(report, minimum_checks=2, required_test_ids={"wbcan-only_check"})


def test_report_rejects_pass_when_expected_and_actual_differ(tmp_path: Path) -> None:
    report = tmp_path / "report.tsv"
    _write_report(report, ["PASS\twbcan-broken\tbroken\t1\t0\n"])

    with pytest.raises(MODULE.ReportError, match="contradicts"):
        MODULE.validate_report(report, minimum_checks=1, required_test_ids={"wbcan-broken"})


def test_report_rejects_missing_or_unexpected_test_ids(tmp_path: Path) -> None:
    report = tmp_path / "report.tsv"
    _write_report(report, ["PASS\twbcan-first\tfirst\t1\t1\n"])

    with pytest.raises(MODULE.ReportError, match=r"missing=.*wbcan-second"):
        MODULE.validate_report(
            report,
            minimum_checks=1,
            required_test_ids={"wbcan-first", "wbcan-second"},
        )


def test_fault_suite_fails_if_report_append_fails() -> None:
    script = TEST_SCRIPT.read_text(encoding="utf-8")

    assert '>> "$REPORT_FILE" || {' in script
    assert "cannot append to test report" in script


def _stress_report(profile_name: str = "developer-smoke") -> dict[str, object]:
    profile = STRESS.profile_config(profile_name)
    producer = {
        "can_id": "0x740",
        "requested": profile.frames_per_producer,
        "sent": profile.frames_per_producer,
        "received": profile.frames_per_producer,
        "lost": 0,
        "duplicate": 0,
        "reordered": 0,
        "unexpected": 0,
        "longest_no_progress_ms": 1,
    }
    stages = [{"name": name, "result": "PASS", "duration_ms": 1} for name in STRESS.REQUIRED_STAGES]
    reconfiguration = next(stage for stage in stages if stage["name"] == "reconfiguration")
    reconfiguration["details"] = {"frames_requested": 400, "status_reads": 600, "fault_rearms": 150}
    drops = next(stage for stage in stages if stage["name"] == "drop_fault_accounting")
    drops["details"] = {
        "drop_tx_expected": 2,
        "drop_rx_expected": 2,
        "intentional_loss": 4,
        "unexplained_loss": 0,
        "recovery_frames": 1,
        "driver_rx_dropped": 2,
    }
    lifecycle = next(stage for stage in stages if stage["name"] == "link_lifecycle")
    lifecycle["details"] = {"cycles": 8, "frames_requested": 500, "status_reads": 800}
    stats = next(stage for stage in stages if stage["name"] == "stats_sampling")
    stats["details"] = {"samples": 10, "regressions": 0}
    saturation = next(stage for stage in stages if stage["name"] == "multi_producer_saturation")
    saturation["details"] = {
        "producer_count": profile.producer_count,
        "frames_per_producer": profile.frames_per_producer,
        "max_no_progress_ms": profile.max_no_progress_ms,
        "unexpected_frames": 0,
        "producers": [{**producer, "can_id": f"0x{0x740 + index:03x}"} for index in range(profile.producer_count)],
    }
    tx_full = next(stage for stage in stages if stage["name"] == "repeated_tx_full")
    tx_full["details"] = {"attempts": profile.tx_full_attempts, "delivered_once": profile.tx_full_attempts}
    slow_receiver = next(stage for stage in stages if stage["name"] == "slow_receiver")
    slow_receiver["details"] = {
        "sent": profile.slow_receiver_frames,
        "received": 1,
        "expected_socket_loss": profile.slow_receiver_frames - 1,
        "duplicate": 0,
        "unexpected": 0,
        "driver_rx_dropped": 0,
    }
    reload_stage = next(stage for stage in stages if stage["name"] == "unload_reload")
    reload_stage["details"] = {
        "requested_cycles": profile.reload_cycles,
        "completed_cycles": profile.reload_cycles,
        "module_absence_checks": profile.reload_cycles,
        "interface_absence_checks": profile.reload_cycles,
        "debugfs_absence_checks": profile.reload_cycles,
        "post_reload_frames": profile.reload_cycles,
        "stale_frames": 0,
        "open_socket_count": 0,
        "live_thread_count": 0,
    }
    cleanup = next(stage for stage in stages if stage["name"] == "cleanup")
    cleanup["details"] = {
        "open_socket_count": 0,
        "live_thread_count": 0,
        "module_loaded": True,
        "interface_present": True,
        "debugfs_present": True,
        "link_active": True,
        "fault_cleared": True,
        "subprocesses_reaped": True,
    }
    return STRESS._build_report(
        interface="wbcan0",
        module_path=STRESS_PATH.with_name("wbcan.ko"),
        profile=profile,
        started_at=1,
        completed_at=2,
        elapsed_ms=1,
        result="PASS",
        stages=stages,
    )


def test_stress_report_accepts_complete_virtual_pass(tmp_path: Path) -> None:
    report = _stress_report()
    path = tmp_path / "stress.json"

    STRESS.write_stress_report(path, report)
    STRESS.validate_stress_report(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("mutation", ["missing_stage", "failed_without_error", "physical_scope", "duplicate_stage"])
def test_stress_report_rejects_incomplete_or_untruthful_evidence(mutation: str) -> None:
    report = _stress_report()
    stages = report["stages"]
    assert isinstance(stages, list)
    if mutation == "missing_stage":
        stages.pop()
    elif mutation == "failed_without_error":
        report["result"] = "FAIL"
        stages[0]["result"] = "FAIL"
    elif mutation == "physical_scope":
        report["scope"] = "physical-can"
    else:
        stages.append(dict(stages[0]))

    with pytest.raises(ValueError):
        STRESS.validate_stress_report(report)


def test_failed_stress_report_rejects_mixed_not_executed_stage() -> None:
    report = _stress_report()
    report["result"] = "FAIL"
    stages = report["stages"]
    assert isinstance(stages, list)
    stages[0]["result"] = "FAIL"
    stages[0]["error"] = "injected failure"
    cleanup = stages[-1]
    cleanup["result"] = "NOT_EXECUTED"
    cleanup["error"] = "cleanup was not run"
    stages[:] = [stages[0], cleanup]

    with pytest.raises(ValueError, match="cannot contain a NOT_EXECUTED stage"):
        STRESS.validate_stress_report(report)


def test_delivery_analysis_reports_loss_duplicate_reordering_and_progress() -> None:
    metrics = STRESS.analyze_delivery(
        {0x740: [0, 1, 2, 3]},
        {0x740: [0, 2, 2, 1, 9]},
        {0x740: [1.0, 1.01, 1.03, 1.04, 1.08]},
        requested=4,
    )

    assert metrics == [
        {
            "can_id": "0x740",
            "requested": 4,
            "sent": 4,
            "received": 5,
            "lost": 1,
            "duplicate": 1,
            "reordered": 1,
            "unexpected": 1,
            "longest_no_progress_ms": 40,
        }
    ]

    metrics = STRESS.analyze_delivery(
        {0x740: [0]},
        {0x740: [0]},
        {0x740: [10.25]},
        requested=1,
        producer_started={0x740: 10.0},
    )
    assert metrics[0]["longest_no_progress_ms"] == 250


def test_saturation_decoder_requires_the_complete_reserved_payload() -> None:
    expected_ids = {0x740}
    valid = STRESS.FRAME.pack(0x740, 8, (7).to_bytes(4, "big") + b"\0" * 4)

    assert STRESS.decode_saturation_frame(valid, expected_ids) == (0x740, 7)
    assert (
        STRESS.decode_saturation_frame(
            STRESS.FRAME.pack(0x740, 8, (7).to_bytes(4, "big") + b"bad!"),
            expected_ids,
        )
        is None
    )
    assert (
        STRESS.decode_saturation_frame(
            STRESS.FRAME.pack(0x740, 7, (7).to_bytes(4, "big") + b"\0" * 4),
            expected_ids,
        )
        is None
    )


def test_stress_report_rejects_saturation_delivery_anomaly() -> None:
    report = _stress_report()
    stages = report["stages"]
    assert isinstance(stages, list)
    saturation = next(stage for stage in stages if stage["name"] == "multi_producer_saturation")
    saturation["details"]["producers"][0]["lost"] = 1

    with pytest.raises(ValueError, match="delivery anomalies"):
        STRESS.validate_stress_report(report)

    report = _stress_report()
    stages = report["stages"]
    assert isinstance(stages, list)
    saturation = next(stage for stage in stages if stage["name"] == "multi_producer_saturation")
    saturation["details"]["unexpected_frames"] = 1

    with pytest.raises(ValueError, match="unexpected frames"):
        STRESS.validate_stress_report(report)


def test_stress_report_records_but_accepts_complete_reordered_delivery() -> None:
    report = _stress_report()
    stages = report["stages"]
    assert isinstance(stages, list)
    saturation = next(stage for stage in stages if stage["name"] == "multi_producer_saturation")
    saturation["details"]["producers"][0]["reordered"] = 3

    STRESS.validate_stress_report(report)


def test_stress_report_rejects_tx_full_or_slow_receiver_anomaly() -> None:
    report = _stress_report()
    stages = report["stages"]
    assert isinstance(stages, list)
    tx_full = next(stage for stage in stages if stage["name"] == "repeated_tx_full")
    tx_full["details"]["delivered_once"] = 15
    with pytest.raises(ValueError, match="exactly once"):
        STRESS.validate_stress_report(report)

    report = _stress_report()
    stages = report["stages"]
    slow_receiver = next(stage for stage in stages if stage["name"] == "slow_receiver")
    slow_receiver["details"]["driver_rx_dropped"] = 1
    with pytest.raises(ValueError, match="driver anomalies"):
        STRESS.validate_stress_report(report)


def test_release_profile_is_fixed_and_has_repeated_baseline_provenance() -> None:
    report = _stress_report("release")

    STRESS.validate_stress_report(report)
    assert report["budget"]["baseline"]["run_count"] >= 3
    assert report["budget"]["baseline"]["duration_ms"] == STRESS.profile_config("release").baseline_duration_ms
    with pytest.raises(ValueError, match="release profile is fixed"):
        STRESS.resolve_profile("release", reload_cycles=1)

    report["budget"]["baseline"]["duration_ms"] += 1
    with pytest.raises(ValueError, match="baseline duration"):
        STRESS.validate_stress_report(report)

    report = _stress_report("release")
    report["budget"]["baseline"]["runs"][0]["observed_duration_ms"] += 1
    with pytest.raises(ValueError, match=r"observed maximum|fixed evidence"):
        STRESS.validate_stress_report(report)


def test_stress_report_rejects_over_budget_or_incomplete_reload_evidence() -> None:
    report = _stress_report()
    report["elapsed_ms"] = STRESS.profile_config("developer-smoke").max_duration_ms + 1
    report["budget"]["elapsed_ms"] = report["elapsed_ms"]
    report["budget"]["within_budget"] = False
    with pytest.raises(ValueError, match="exceeded its wall-clock budget"):
        STRESS.validate_stress_report(report)

    report = _stress_report()
    stages = report["stages"]
    assert isinstance(stages, list)
    stages.pop(-2)  # remove unload_reload while retaining the cleanup suffix
    with pytest.raises(ValueError, match=r"ordered execution prefix|every required"):
        STRESS.validate_stress_report(report)


def test_stress_report_rejects_resource_leak_and_profile_inconsistency() -> None:
    report = _stress_report()
    cleanup = next(stage for stage in report["stages"] if stage["name"] == "cleanup")
    cleanup["details"]["open_socket_count"] = 1
    with pytest.raises(ValueError, match="live resources"):
        STRESS.validate_stress_report(report)

    report = _stress_report()
    report["profile_config"]["max_no_progress_ms"] = 1
    with pytest.raises(ValueError, match=r"fixed release|profile_config changed"):
        STRESS.validate_stress_report(report)

    for field in ("fault_cleared", "subprocesses_reaped"):
        report = _stress_report()
        cleanup = next(stage for stage in report["stages"] if stage["name"] == "cleanup")
        cleanup["details"][field] = False
        with pytest.raises(ValueError, match=f"did not verify {field}"):
            STRESS.validate_stress_report(report)


def test_probe_command_can_restore_after_an_expired_workload_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = STRESS.Probe("wbcan0", Path("/tmp/wbcan-debugfs"), max_duration_ms=1)
    probe.deadline = 0
    calls: list[tuple[object, ...]] = []

    def fake_run(*arguments: object, **kwargs: object) -> None:
        calls.append(arguments)

    monkeypatch.setattr(STRESS.subprocess, "run", fake_run)
    probe.command("true", enforce_budget=False)
    assert calls
    with pytest.raises(STRESS.BudgetExceededError):
        probe.command("true")


def test_concurrent_worker_failure_is_reported_and_aborts_siblings() -> None:
    probe = STRESS.Probe("wbcan0", Path("/tmp/wbcan-debugfs"))

    def fail() -> None:
        raise RuntimeError("worker failed")

    worker = threading.Thread(target=probe.capture, args=(fail,), name="failing-worker")
    worker.start()
    worker.join(timeout=1)

    with pytest.raises(ExceptionGroup, match="worker failures"):
        probe.finish_threads(worker)
    assert probe.abort.is_set()


def test_cleanup_restore_retries_but_reports_recovery_after_first_failure() -> None:
    probe = STRESS.Probe("wbcan0", Path("/tmp/wbcan-debugfs"))
    attempts: list[int] = []

    def restore() -> None:
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            raise RuntimeError("transient restoration failure")

    probe._restore_device = restore  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="second attempt"):
        probe._restore_for_cleanup()
    assert attempts == [1, 2]


def test_stress_preflight_converts_debugfs_permission_errors_to_not_executed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protected = Path("/tmp/wbcan-protected-debugfs")
    original_is_dir = Path.is_dir

    def deny_protected(path: Path) -> bool:
        if path == protected:
            raise PermissionError("debugfs access denied")
        return original_is_dir(path)

    monkeypatch.setattr(Path, "is_dir", deny_protected)
    with pytest.raises(STRESS.NotExecutedError, match="debugfs directory is unavailable"):
        STRESS._preflight("wbcan0", protected, Path("/tmp/missing-wbcan.ko"))


def test_failed_probe_persists_a_valid_fail_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(STRESS, "_preflight", lambda interface, debugfs, module_path: None)

    def fail_reconfiguration(self: object) -> None:
        raise RuntimeError("synthetic stage failure")

    def clean(self: object) -> dict[str, int | bool]:
        return {
            "open_socket_count": 0,
            "live_thread_count": 0,
            "module_loaded": True,
            "interface_present": True,
            "debugfs_present": True,
            "link_active": True,
            "fault_cleared": True,
            "subprocesses_reaped": True,
        }

    monkeypatch.setattr(STRESS.Probe, "exercise_reconfiguration", fail_reconfiguration)
    monkeypatch.setattr(STRESS.Probe, "cleanup", clean)
    report_path = tmp_path / "failed-stress.json"

    with pytest.raises(RuntimeError, match="synthetic stage failure"):
        STRESS.run_probe("wbcan0", Path("/tmp/wbcan-debugfs"), report_path)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    STRESS.validate_stress_report(report)
    assert report["result"] == "FAIL"


def test_stress_report_accepts_truthful_not_executed_result() -> None:
    profile = STRESS.profile_config("developer-smoke")
    report = STRESS._build_report(
        interface="wbcan0",
        module_path=STRESS_PATH.with_name("wbcan.ko"),
        profile=profile,
        started_at=1,
        completed_at=2,
        elapsed_ms=1,
        result="NOT_EXECUTED",
        stages=[],
        reason="matching kernel headers are unavailable",
    )

    STRESS.validate_stress_report(report)
    report.pop("not_executed_reason")
    with pytest.raises(ValueError, match="requires a reason"):
        STRESS.validate_stress_report(report)


def test_stress_entrypoints_select_release_and_preserve_before_after_diagnostics() -> None:
    makefile = STRESS_MAKEFILE.read_text(encoding="utf-8")
    script = TEST_SCRIPT.read_text(encoding="utf-8")
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "STRESS_PROFILE ?= release" in makefile
    assert "stress-smoke:" in makefile
    assert "stress-release:" in makefile
    assert "--require-pass" in makefile
    assert '--profile "$STRESS_PROFILE"' in script
    assert "WBCAN_STRESS_PROFILE: release" in workflow
    assert "Capture pre-fault-suite resource snapshot" in workflow
    assert "--before-slabinfo" in workflow
    assert "wbcan-slabinfo-before.txt" in workflow


def _latency_activity(profile: str) -> dict[str, object]:
    if profile == "idle":
        return {"kind": "idle", "iterations": 0}
    if profile == "status-readers":
        return {"kind": "status-readers", "iterations": 12}
    return {
        "kind": "controlled-load",
        "iterations": 15,
        "cpu": {
            "worker_count": 1,
            "operation": LATENCY.CPU_OPERATION,
            "iterations": 10,
            "worker_iterations": [10],
        },
        "io": {
            "worker_count": 1,
            "operation": LATENCY.IO_OPERATION,
            "iterations": 5,
            "worker_iterations": [5],
            "bytes_written": 5 * LATENCY.IO_WORK_BYTES,
            "maximum_file_size_bytes": LATENCY.IO_WORK_BYTES,
        },
    }


def _latency_configuration(profile: str) -> dict[str, object]:
    if profile == "idle":
        return {"kind": "idle"}
    if profile == "status-readers":
        return {"kind": "status-readers", "status_path": "/debug/status"}
    return {
        "kind": "controlled-load",
        "cpu_workers": 1,
        "io_workers": 1,
        "cpu_operation": LATENCY.CPU_OPERATION,
        "io_operation": LATENCY.IO_OPERATION,
        "io_file_size_bytes": LATENCY.IO_WORK_BYTES,
        "load_directory": "/tmp",
    }


def _latency_report(profile: str = "idle", repetitions: int = 1) -> dict[str, object]:
    runs = [
        {
            "run_index": index,
            "load_activity": _latency_activity(profile),
            "elapsed_ns": 1_000_000 + index,
            "process_cpu_ns": 500_000 + index,
            "throughput_fps": 10_000 - index,
            "loss": 0,
            "duplicates": 0,
            "reordered": 0,
            "latency": LATENCY.summarize(list(range(index, index + 10)), deadline_ns=8),
        }
        for index in range(1, repetitions + 1)
    ]
    report = {
        "schema_version": LATENCY.SCHEMA_VERSION,
        "scope": "virtual-wbcan-userspace",
        "result": "PASS",
        "interface": "wbcan0",
        "commit": "test-commit",
        "kernel": "test-kernel",
        "kernel_config_sha256": "unavailable",
        "preemption_model": "unknown",
        "cpu_count": 2,
        "cpu_affinity": [0, 1],
        "load_profile": profile,
        "load_configuration": _latency_configuration(profile),
        "clock": "monotonic_ns",
        "warmup_count": 10,
        "sample_count": 10,
        "message_size": 8,
        "can_id": 0x760,
        "deadline_ns": 8,
        "repetition_count": repetitions,
        "completed_repetitions": repetitions,
        "run_budget": {
            "maximum_repetitions": LATENCY.MAX_REPETITIONS,
            "maximum_samples_per_run": LATENCY.MAX_SAMPLES,
            "requested_repetitions": repetitions,
            "warmup_frames_per_run": 10,
            "measured_frames_per_run": 10,
            "total_frame_attempts": repetitions * 20,
        },
        "runs": runs,
    }
    report["observed_envelope"] = LATENCY.aggregate_runs(runs)
    return report


def test_latency_summary_uses_nearest_rank_and_population_jitter() -> None:
    summary = LATENCY.summarize(list(range(1, 101)), deadline_ns=90)

    assert summary["p50_ns"] == 50
    assert summary["p95_ns"] == 95
    assert summary["p99_ns"] == 99
    assert summary["max_ns"] == 100
    assert summary["jitter_ns"] == 29
    assert summary["missed_deadline_count"] == 10


def test_latency_report_accepts_complete_virtual_evidence(tmp_path: Path) -> None:
    report = _latency_report()
    path = tmp_path / "latency.json"

    LATENCY.write_report(path, report)
    LATENCY.validate_report(json.loads(path.read_text(encoding="utf-8")))


def test_latency_json_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    report = tmp_path / "duplicate.json"
    report.write_text('{"result":"PASS","result":"FAIL"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON key"):
        LATENCY.load_json(report)


def test_latency_report_accepts_truthful_failure_and_not_executed_states() -> None:
    failed = _latency_report()
    failed["result"] = "FAIL"
    failed["error"] = "TimeoutError: frame was not received"
    del failed["observed_envelope"]
    LATENCY.validate_report(failed)

    not_executed = _latency_report()
    not_executed.update(
        {
            "result": "NOT_EXECUTED",
            "completed_repetitions": 0,
            "runs": [],
            "error": "wbcan interface is unavailable",
        }
    )
    del not_executed["observed_envelope"]
    LATENCY.validate_report(not_executed)

    not_executed["completed_repetitions"] = 1
    not_executed["runs"] = failed["runs"]
    with pytest.raises(ValueError, match="NOT_EXECUTED"):
        LATENCY.validate_report(not_executed)


@pytest.mark.parametrize(
    "mutation",
    ["physical_scope", "loss", "percentile_order", "bad_clock", "partial", "run_gap", "bad_envelope", "extra"],
)
def test_latency_report_rejects_invalid_or_untruthful_evidence(mutation: str) -> None:
    report = _latency_report()
    if mutation == "physical_scope":
        report["scope"] = "physical-can"
    elif mutation == "loss":
        report["runs"][0]["loss"] = 1
    elif mutation == "percentile_order":
        report["runs"][0]["latency"]["p95_ns"] = 0
    elif mutation == "bad_clock":
        report["clock"] = "wall-clock"
    elif mutation == "partial":
        report["sample_count"] = 9
    elif mutation == "run_gap":
        report["runs"][0]["run_index"] = 2
    elif mutation == "extra":
        report["physical_can"] = "PASS"
    else:
        report["observed_envelope"]["latency"]["p99_ns"]["maximum"] += 1

    with pytest.raises(ValueError):
        LATENCY.validate_report(report)


def test_latency_summary_rejects_negative_or_empty_samples() -> None:
    with pytest.raises(ValueError):
        LATENCY.summarize([], deadline_ns=None)
    with pytest.raises(ValueError):
        LATENCY.summarize([1, -1], deadline_ns=None)


def test_latency_report_accepts_observed_status_reader_load() -> None:
    report = _latency_report("status-readers")

    LATENCY.validate_report(report)


def test_latency_report_rejects_unobserved_or_mismatched_load() -> None:
    report = _latency_report("status-readers")
    report["runs"][0]["load_activity"]["kind"] = "idle"
    with pytest.raises(ValueError, match="load activity"):
        LATENCY.validate_report(report)

    report = _latency_report("status-readers")
    report["runs"][0]["load_activity"]["iterations"] = 0
    with pytest.raises(ValueError, match="requires observed reads"):
        LATENCY.validate_report(report)


def test_latency_report_accepts_repeated_controlled_load() -> None:
    report = _latency_report("controlled-load", repetitions=3)

    LATENCY.validate_report(report)
    assert report["observed_envelope"]["run_count"] == 3
    assert report["observed_envelope"]["latency"]["p99_ns"] == {
        "minimum": 10,
        "nearest_rank_median": 11,
        "maximum": 12,
    }


@pytest.mark.parametrize(
    "mutation", ["missing_cpu_activity", "idle_worker", "wrong_bytes", "unbounded_file", "total_mismatch"]
)
def test_latency_report_rejects_unobserved_or_unbounded_controlled_load(mutation: str) -> None:
    report = _latency_report("controlled-load", repetitions=3)
    activity = report["runs"][0]["load_activity"]
    if mutation == "missing_cpu_activity":
        del activity["cpu"]
    elif mutation == "idle_worker":
        activity["io"]["worker_iterations"] = [0]
    elif mutation == "wrong_bytes":
        activity["io"]["bytes_written"] += 1
    elif mutation == "unbounded_file":
        activity["io"]["maximum_file_size_bytes"] *= 2
    else:
        activity["iterations"] += 1

    with pytest.raises(ValueError, match="controlled latency"):
        LATENCY.validate_report(report)


def test_controlled_load_workers_are_observed_and_leave_no_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_measure(*_args: object) -> list[int]:
        time.sleep(0.05)
        return list(range(1, 11))

    monkeypatch.setattr(LATENCY, "measure", fake_measure)

    samples, activity, elapsed_ns, process_cpu_ns = LATENCY.measure_profile(
        "wbcan0",
        0,
        10,
        0x760,
        "controlled-load",
        None,
        1,
        1,
        tmp_path,
    )

    assert samples == list(range(1, 11))
    assert elapsed_ns > 0
    assert process_cpu_ns >= 0
    assert activity["cpu"]["worker_iterations"][0] > 0
    assert activity["io"]["worker_iterations"][0] > 0
    assert activity["io"]["maximum_file_size_bytes"] == LATENCY.IO_WORK_BYTES
    assert not list(tmp_path.iterdir())
    assert not any(
        process.name.startswith("latency-") and process.is_alive()
        for process in LATENCY.multiprocessing.active_children()
    )


def test_controlled_load_supports_the_spawn_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LATENCY, "_worker_context", lambda: LATENCY.multiprocessing.get_context("spawn"))

    def fake_measure(*_args: object) -> list[int]:
        time.sleep(0.05)
        return list(range(1, 11))

    monkeypatch.setattr(LATENCY, "measure", fake_measure)

    samples, activity, _elapsed_ns, _process_cpu_ns = LATENCY.measure_profile(
        "wbcan0", 0, 10, 0x760, "controlled-load", None, 1, 1, tmp_path
    )

    assert samples == list(range(1, 11))
    assert activity["cpu"]["worker_iterations"][0] > 0
    assert activity["io"]["worker_iterations"][0] > 0
    assert not list(tmp_path.iterdir())


def test_controlled_load_setup_is_outside_the_timed_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LATENCY, "_cpu_load_worker", _delayed_ready_cpu_worker)

    def fake_measure(*_args: object) -> list[int]:
        time.sleep(0.03)
        return list(range(1, 11))

    monkeypatch.setattr(LATENCY, "measure", fake_measure)
    started = time.monotonic()

    _samples, _activity, elapsed_ns, _process_cpu_ns = LATENCY.measure_profile(
        "wbcan0", 0, 10, 0x760, "controlled-load", None, 1, 1, tmp_path
    )

    total_elapsed = time.monotonic() - started
    assert total_elapsed >= 0.15
    assert total_elapsed - (elapsed_ns / 1_000_000_000) >= 0.1


def test_controlled_load_worker_failure_is_visible_and_cleanup_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(LATENCY, "WORKER_READY_TIMEOUT_S", 0.1)
    monkeypatch.setattr(LATENCY.os, "pwrite", lambda *_args: 0)
    measurement_called = False

    def unexpected_measurement(*_args: object) -> list[int]:
        nonlocal measurement_called
        measurement_called = True
        return list(range(1, 11))

    monkeypatch.setattr(LATENCY, "measure", unexpected_measurement)

    with pytest.raises(RuntimeError, match="short write"):
        LATENCY.measure_profile("wbcan0", 0, 10, 0x760, "controlled-load", None, 1, 1, tmp_path)

    assert not measurement_called
    assert not list(tmp_path.iterdir())
    assert not any(
        process.name.startswith("latency-") and process.is_alive()
        for process in LATENCY.multiprocessing.active_children()
    )


def test_controlled_load_stops_and_verifies_a_timed_out_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LATENCY, "WORKER_READY_TIMEOUT_S", 0.1)
    monkeypatch.setattr(LATENCY, "WORKER_JOIN_TIMEOUT_S", 0.01)
    monkeypatch.setattr(LATENCY, "_cpu_load_worker", _ready_then_sleeping_latency_worker)

    def fake_measure(*_args: object) -> list[int]:
        return list(range(1, 11))

    monkeypatch.setattr(LATENCY, "measure", fake_measure)

    with pytest.raises(RuntimeError, match="did not stop cooperatively"):
        LATENCY.measure_profile("wbcan0", 0, 10, 0x760, "controlled-load", None, 1, 1, tmp_path)

    assert not any(
        process.name.startswith("latency-") and process.is_alive()
        for process in LATENCY.multiprocessing.active_children()
    )


def test_controlled_load_rejects_a_nonzero_worker_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LATENCY, "WORKER_READY_TIMEOUT_S", 0.1)
    monkeypatch.setattr(LATENCY, "_cpu_load_worker", _nonzero_latency_worker)

    with pytest.raises(RuntimeError, match="exited with status 7"):
        LATENCY.measure_profile("wbcan0", 0, 10, 0x760, "controlled-load", None, 1, 1, tmp_path)

    assert not any(
        process.name.startswith("latency-") and process.is_alive()
        for process in LATENCY.multiprocessing.active_children()
    )


def test_latency_campaign_accepts_comparable_repeated_profiles(tmp_path: Path) -> None:
    idle = _latency_report("idle", repetitions=3)
    controlled = _latency_report("controlled-load", repetitions=3)
    campaign = LATENCY_CAMPAIGN.build_campaign(idle, controlled)
    path = tmp_path / "campaign.json"

    LATENCY_CAMPAIGN.write_campaign(path, campaign)
    LATENCY_CAMPAIGN.validate_campaign(json.loads(path.read_text(encoding="utf-8")))
    assert campaign["threshold_policy"] == LATENCY_CAMPAIGN.THRESHOLD_POLICY
    assert campaign["observed_comparison"]["interpretation"] == "informational-only"
    assert campaign["claims"]["physical_can"] == "NOT_EXECUTED"


@pytest.mark.parametrize(
    "mutation",
    ["too_few_runs", "environment_mismatch", "digest_mismatch", "invented_threshold", "physical_claim", "extra"],
)
def test_latency_campaign_rejects_incomplete_or_unsupported_evidence(mutation: str) -> None:
    idle = _latency_report("idle", repetitions=3)
    controlled = _latency_report("controlled-load", repetitions=3)
    campaign = LATENCY_CAMPAIGN.build_campaign(idle, controlled)
    if mutation == "too_few_runs":
        controlled = _latency_report("controlled-load", repetitions=2)
        with pytest.raises(ValueError, match="at least"):
            LATENCY_CAMPAIGN.build_campaign(idle, controlled)
        return
    if mutation == "environment_mismatch":
        controlled["can_id"] = 0x761
        with pytest.raises(ValueError, match="not comparable"):
            LATENCY_CAMPAIGN.build_campaign(idle, controlled)
        return
    if mutation == "digest_mismatch":
        campaign["profiles"]["idle"]["source_sha256"] = "0" * 64
    elif mutation == "invented_threshold":
        campaign["threshold_policy"] = "p99-under-100us"
    elif mutation == "physical_claim":
        campaign["claims"]["physical_can"] = "PASS"
    else:
        campaign["performance_sla"] = "PASS"

    with pytest.raises(ValueError):
        LATENCY_CAMPAIGN.validate_campaign(campaign)


def test_kernel_job_records_repeated_idle_and_controlled_load_campaign() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert '--repetitions 3 --report "$IDLE_REPORT"' in workflow
    assert '--repetitions 3 --report "$CONTROLLED_REPORT"' in workflow
    assert "--load-profile controlled-load --cpu-load-workers 2 --io-load-workers 1" in workflow
    assert 'validate_latency_campaign.py "$IDLE_REPORT" "$CONTROLLED_REPORT"' in workflow
    assert "Status: **$status**" in workflow
    assert "observational evidence, not an SLA" in workflow


def test_wbcan_status_snapshot_does_not_take_tx_lock_or_format_under_private_lock() -> None:
    source = DRIVER_PATH.read_text(encoding="utf-8")
    status_show = source.split("static int wbcan_status_show", 1)[1].split("static int wbcan_status_open", 1)[0]

    assert "netif_tx_lock" not in status_show
    assert status_show.index("spin_unlock_irqrestore") < status_show.index("seq_printf")


def test_wbcan_initializes_a_stopped_queue_before_registration() -> None:
    source = DRIVER_PATH.read_text(encoding="utf-8")
    init = source.split("static int __init wbcan_init", 1)[1].split("static void __exit wbcan_exit", 1)[0]

    state_offset = init.index("WRITE_ONCE(priv->can.state, CAN_STATE_STOPPED);")
    stop_offset = init.index("netif_stop_queue(wbcan_dev);")
    register_offset = init.index("register_candev(wbcan_dev)")

    assert state_offset < stop_offset < register_offset


def test_kernel_diagnostics_pass_report_requires_empty_warning_matches(tmp_path: Path) -> None:
    dmesg = tmp_path / "dmesg.log"
    slabinfo = tmp_path / "slabinfo"
    meminfo = tmp_path / "meminfo"
    before_slabinfo = tmp_path / "slabinfo-before"
    before_meminfo = tmp_path / "meminfo-before"
    dmesg.write_text("boot WARNING: unrelated\ntest-marker\nwbcan: registered\n", encoding="ascii")
    slabinfo.write_text("slabinfo - version: 2.1\n", encoding="ascii")
    meminfo.write_text("MemTotal: 1 kB\n", encoding="ascii")
    before_slabinfo.write_text("slabinfo - version: 2.1\n", encoding="ascii")
    before_meminfo.write_text("MemTotal: 1 kB\n", encoding="ascii")

    report = DIAGNOSTICS.build_report(
        dmesg,
        slabinfo,
        meminfo,
        "test-kernel",
        "test-marker",
        before_slabinfo=before_slabinfo,
        before_meminfo=before_meminfo,
    )

    assert report["result"] == "PASS"
    DIAGNOSTICS.validate_report(report)


def test_kernel_diagnostics_rejects_warning_signatures_and_malformed_pass() -> None:
    assert DIAGNOSTICS.scan_dmesg("INFO ok\nBUG: bad\nlockdep: held\n") == ["BUG: bad", "lockdep: held"]
    with pytest.raises(ValueError, match="cannot contain warnings"):
        DIAGNOSTICS.validate_report(
            {
                "schema_version": DIAGNOSTICS.SCHEMA_VERSION,
                "scope": "virtual-wbcan-kernel-job",
                "result": "PASS",
                "kernel": "test",
                "marker": "marker",
                "dmesg_path": "dmesg",
                "slabinfo_path": "slab",
                "meminfo_path": "mem",
                "dmesg_bytes": 1,
                "scoped_dmesg_bytes": 1,
                "slabinfo_bytes": 1,
                "meminfo_bytes": 1,
                "resource_snapshots": {
                    "before": {
                        "slabinfo_path": "before-slab",
                        "meminfo_path": "before-mem",
                        "slabinfo_bytes": 1,
                        "meminfo_bytes": 1,
                    },
                    "after": {
                        "slabinfo_path": "slab",
                        "meminfo_path": "mem",
                        "slabinfo_bytes": 1,
                        "meminfo_bytes": 1,
                    },
                },
                "warnings": ["BUG: bad"],
            }
        )


def test_kernel_diagnostics_requires_marker_and_scans_only_scoped_log(tmp_path: Path) -> None:
    dmesg = tmp_path / "dmesg.log"
    slabinfo = tmp_path / "slabinfo"
    meminfo = tmp_path / "meminfo"
    before_slabinfo = tmp_path / "slabinfo-before"
    before_meminfo = tmp_path / "meminfo-before"
    dmesg.write_text("boot WARNING: unrelated\nmarker\nBUG: wbcan failure\n", encoding="ascii")
    slabinfo.write_text("slab\n", encoding="ascii")
    meminfo.write_text("mem\n", encoding="ascii")
    before_slabinfo.write_text("slab\n", encoding="ascii")
    before_meminfo.write_text("mem\n", encoding="ascii")

    report = DIAGNOSTICS.build_report(
        dmesg,
        slabinfo,
        meminfo,
        "test",
        "marker",
        before_slabinfo=before_slabinfo,
        before_meminfo=before_meminfo,
    )
    assert report["warnings"] == ["BUG: wbcan failure"]
    with pytest.raises(ValueError, match="marker is missing"):
        DIAGNOSTICS.build_report(
            dmesg,
            slabinfo,
            meminfo,
            "test",
            "absent-marker",
            before_slabinfo=before_slabinfo,
            before_meminfo=before_meminfo,
        )


def test_kernel_diagnostics_requires_consistent_before_after_snapshots(tmp_path: Path) -> None:
    dmesg = tmp_path / "dmesg.log"
    slabinfo = tmp_path / "slabinfo"
    meminfo = tmp_path / "meminfo"
    before_slabinfo = tmp_path / "slabinfo-before"
    before_meminfo = tmp_path / "meminfo-before"
    dmesg.write_text("marker\nwbcan: clean\n", encoding="ascii")
    for path in (slabinfo, meminfo, before_slabinfo, before_meminfo):
        path.write_text("resource snapshot\n", encoding="ascii")

    report = DIAGNOSTICS.build_report(
        dmesg,
        slabinfo,
        meminfo,
        "test",
        "marker",
        before_slabinfo=before_slabinfo,
        before_meminfo=before_meminfo,
    )
    report["resource_snapshots"]["after"]["slabinfo_bytes"] += 1
    with pytest.raises(ValueError, match="disagrees"):
        DIAGNOSTICS.validate_report(report)

    report = DIAGNOSTICS.build_report(
        dmesg,
        slabinfo,
        meminfo,
        "test",
        "marker",
        before_slabinfo=before_slabinfo,
        before_meminfo=before_meminfo,
    )
    report["resource_snapshots"]["before"]["meminfo_bytes"] = 0
    with pytest.raises(ValueError, match="invalid meminfo_bytes"):
        DIAGNOSTICS.validate_report(report)

    report = DIAGNOSTICS.build_report(
        dmesg,
        slabinfo,
        meminfo,
        "test",
        "marker",
        before_slabinfo=slabinfo,
        before_meminfo=before_meminfo,
    )
    with pytest.raises(ValueError, match="snapshots must be distinct"):
        DIAGNOSTICS.validate_report(report)


def test_kernel_diagnostics_builder_requires_before_snapshots(tmp_path: Path) -> None:
    dmesg = tmp_path / "dmesg.log"
    slabinfo = tmp_path / "slabinfo"
    meminfo = tmp_path / "meminfo"
    dmesg.write_text("marker\n", encoding="ascii")
    slabinfo.write_text("slab\n", encoding="ascii")
    meminfo.write_text("mem\n", encoding="ascii")

    with pytest.raises(ValueError, match="before slabinfo and meminfo"):
        DIAGNOSTICS.build_report(dmesg, slabinfo, meminfo, "test", "marker")
