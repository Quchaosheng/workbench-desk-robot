import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "kernel" / "wbcan" / "validate_test_report.py"
TEST_SCRIPT = ROOT / "kernel" / "wbcan" / "test_wbcan.sh"
STRESS_PATH = ROOT / "kernel" / "wbcan" / "test_state_concurrency.py"
LATENCY_PATH = ROOT / "kernel" / "wbcan" / "test_latency.py"
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


def _latency_report() -> dict[str, object]:
    return {
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
        "load_profile": "idle",
        "load_activity": {"kind": "idle", "iterations": 0},
        "elapsed_ns": 1_000_000,
        "process_cpu_ns": 500_000,
        "throughput_fps": 10_000,
        "clock": "monotonic_ns",
        "warmup_count": 10,
        "sample_count": 10,
        "message_size": 8,
        "can_id": 0x760,
        "loss": 0,
        "duplicates": 0,
        "reordered": 0,
        "latency": LATENCY.summarize(list(range(1, 11)), deadline_ns=8),
    }


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


@pytest.mark.parametrize("mutation", ["physical_scope", "loss", "percentile_order", "bad_clock", "partial"])
def test_latency_report_rejects_invalid_or_untruthful_evidence(mutation: str) -> None:
    report = _latency_report()
    if mutation == "physical_scope":
        report["scope"] = "physical-can"
    elif mutation == "loss":
        report["loss"] = 1
    elif mutation == "percentile_order":
        report["latency"]["p95_ns"] = 0
    elif mutation == "bad_clock":
        report["clock"] = "wall-clock"
    else:
        report["sample_count"] = 9

    with pytest.raises(ValueError):
        LATENCY.validate_report(report)


def test_latency_summary_rejects_negative_or_empty_samples() -> None:
    with pytest.raises(ValueError):
        LATENCY.summarize([], deadline_ns=None)
    with pytest.raises(ValueError):
        LATENCY.summarize([1, -1], deadline_ns=None)


def test_latency_report_accepts_observed_status_reader_load() -> None:
    report = _latency_report()
    report["load_profile"] = "status-readers"
    report["load_activity"] = {"kind": "status-readers", "iterations": 12}

    LATENCY.validate_report(report)


def test_latency_report_rejects_unobserved_or_mismatched_load() -> None:
    report = _latency_report()
    report["load_profile"] = "status-readers"
    with pytest.raises(ValueError, match="load activity"):
        LATENCY.validate_report(report)

    report["load_activity"] = {"kind": "status-readers", "iterations": 0}
    with pytest.raises(ValueError, match="requires observed reads"):
        LATENCY.validate_report(report)
