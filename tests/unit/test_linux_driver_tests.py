import importlib.util
import json
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DRIVER_PATH = ROOT / "kernel" / "wbcan" / "wbcan.c"
CI_PATH = ROOT / ".github" / "workflows" / "ci.yml"
MODULE_PATH = ROOT / "kernel" / "wbcan" / "validate_test_report.py"
TEST_SCRIPT = ROOT / "kernel" / "wbcan" / "test_wbcan.sh"
STRESS_PATH = ROOT / "kernel" / "wbcan" / "test_state_concurrency.py"
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
LATENCY_SPEC = importlib.util.spec_from_file_location("wbcan_latency", LATENCY_PATH)
assert LATENCY_SPEC and LATENCY_SPEC.loader
LATENCY = importlib.util.module_from_spec(LATENCY_SPEC)
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


def _stress_report() -> dict[str, object]:
    producer = {
        "can_id": "0x740",
        "requested": 10,
        "sent": 10,
        "received": 10,
        "lost": 0,
        "duplicate": 0,
        "reordered": 0,
        "unexpected": 0,
        "longest_no_progress_ms": 1,
    }
    stages = [{"name": name, "result": "PASS", "duration_ms": 1} for name in STRESS.REQUIRED_STAGES]
    saturation = next(stage for stage in stages if stage["name"] == "multi_producer_saturation")
    saturation["details"] = {
        "producer_count": 2,
        "frames_per_producer": 10,
        "producers": [producer, {**producer, "can_id": "0x741"}],
    }
    tx_full = next(stage for stage in stages if stage["name"] == "repeated_tx_full")
    tx_full["details"] = {"attempts": 16, "delivered_once": 16}
    slow_receiver = next(stage for stage in stages if stage["name"] == "slow_receiver")
    slow_receiver["details"] = {
        "sent": 500,
        "received": 100,
        "expected_socket_loss": 400,
        "duplicate": 0,
        "unexpected": 0,
        "driver_rx_dropped": 0,
    }
    return {
        "schema_version": STRESS.REPORT_SCHEMA_VERSION,
        "scope": "virtual-wbcan-only",
        "result": "PASS",
        "interface": "wbcan0",
        "kernel": "test-kernel",
        "python": "3.12.0",
        "started_at": "1",
        "completed_at": "2",
        "stages": stages,
    }


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


def test_stress_report_rejects_saturation_delivery_anomaly() -> None:
    report = _stress_report()
    stages = report["stages"]
    assert isinstance(stages, list)
    saturation = next(stage for stage in stages if stage["name"] == "multi_producer_saturation")
    saturation["details"]["producers"][0]["lost"] = 1

    with pytest.raises(ValueError, match="delivery anomalies"):
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
    monkeypatch.setattr(LATENCY, "measure", lambda *_args: list(range(1, 11)))

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
    assert not any(thread.name.startswith("latency-") for thread in threading.enumerate())


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
    assert not any(thread.name.startswith("latency-") for thread in threading.enumerate())


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
    elif mutation == "digest_mismatch":
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
    workflow = CI_PATH.read_text(encoding="utf-8")

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


def test_kernel_diagnostics_pass_report_requires_empty_warning_matches(tmp_path: Path) -> None:
    dmesg = tmp_path / "dmesg.log"
    slabinfo = tmp_path / "slabinfo"
    meminfo = tmp_path / "meminfo"
    dmesg.write_text("boot WARNING: unrelated\ntest-marker\nwbcan: registered\n", encoding="ascii")
    slabinfo.write_text("slabinfo - version: 2.1\n", encoding="ascii")
    meminfo.write_text("MemTotal: 1 kB\n", encoding="ascii")

    report = DIAGNOSTICS.build_report(dmesg, slabinfo, meminfo, "test-kernel", "test-marker")

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
                "warnings": ["BUG: bad"],
            }
        )


def test_kernel_diagnostics_requires_marker_and_scans_only_scoped_log(tmp_path: Path) -> None:
    dmesg = tmp_path / "dmesg.log"
    slabinfo = tmp_path / "slabinfo"
    meminfo = tmp_path / "meminfo"
    dmesg.write_text("boot WARNING: unrelated\nmarker\nBUG: wbcan failure\n", encoding="ascii")
    slabinfo.write_text("slab\n", encoding="ascii")
    meminfo.write_text("mem\n", encoding="ascii")

    report = DIAGNOSTICS.build_report(dmesg, slabinfo, meminfo, "test", "marker")
    assert report["warnings"] == ["BUG: wbcan failure"]
    with pytest.raises(ValueError, match="marker is missing"):
        DIAGNOSTICS.build_report(dmesg, slabinfo, meminfo, "test", "absent-marker")
