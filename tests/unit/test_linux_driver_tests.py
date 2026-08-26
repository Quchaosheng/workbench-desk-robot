import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "kernel" / "wbcan" / "validate_test_report.py"
TEST_SCRIPT = ROOT / "kernel" / "wbcan" / "test_wbcan.sh"
SPEC = importlib.util.spec_from_file_location("validate_wbcan_report", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


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
