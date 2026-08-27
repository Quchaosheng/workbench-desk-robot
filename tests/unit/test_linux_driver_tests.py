import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "kernel" / "wbcan" / "validate_test_report.py"
TEST_SCRIPT = ROOT / "kernel" / "wbcan" / "test_wbcan.sh"
STRESS_PATH = ROOT / "kernel" / "wbcan" / "test_state_concurrency.py"
SPEC = importlib.util.spec_from_file_location("validate_wbcan_report", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
STRESS_SPEC = importlib.util.spec_from_file_location("wbcan_stress", STRESS_PATH)
assert STRESS_SPEC and STRESS_SPEC.loader
STRESS = importlib.util.module_from_spec(STRESS_SPEC)
STRESS_SPEC.loader.exec_module(STRESS)


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
    return {
        "schema_version": STRESS.REPORT_SCHEMA_VERSION,
        "scope": "virtual-wbcan-only",
        "result": "PASS",
        "interface": "wbcan0",
        "kernel": "test-kernel",
        "python": "3.12.0",
        "started_at": "1",
        "completed_at": "2",
        "stages": [{"name": name, "result": "PASS", "duration_ms": 1} for name in STRESS.REQUIRED_STAGES],
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
