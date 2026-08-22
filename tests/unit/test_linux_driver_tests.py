import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "kernel" / "wbcan" / "validate_test_report.py"
SPEC = importlib.util.spec_from_file_location("validate_wbcan_report", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


HEADER = "result\ttest_id\tname\texpected\tactual\n"


def _write_report(path: Path, rows: list[str]) -> None:
    path.write_text(HEADER + "".join(rows), encoding="utf-8")


def test_report_accepts_unique_passing_checks(tmp_path: Path) -> None:
    report = tmp_path / "report.tsv"
    _write_report(
        report,
        [
            "PASS\twbcan-001\tbaseline delivers frame\t1\t1\n",
            "PASS\twbcan-002\tbus-off recovers\terror-active\terror-active\n",
        ],
    )

    assert MODULE.validate_report(report, minimum_checks=2) == 2


def test_report_rejects_duplicate_ids(tmp_path: Path) -> None:
    report = tmp_path / "report.tsv"
    _write_report(
        report,
        [
            "PASS\twbcan-001\tfirst\t1\t1\n",
            "PASS\twbcan-001\tsecond\t1\t1\n",
        ],
    )

    with pytest.raises(MODULE.ReportError, match="duplicate test_id"):
        MODULE.validate_report(report, minimum_checks=1)


def test_report_rejects_failed_checks(tmp_path: Path) -> None:
    report = tmp_path / "report.tsv"
    _write_report(report, ["FAIL\twbcan-001\tbroken\t1\t0\n"])

    with pytest.raises(MODULE.ReportError, match="failed checks"):
        MODULE.validate_report(report, minimum_checks=1)


def test_report_requires_the_expected_check_count(tmp_path: Path) -> None:
    report = tmp_path / "report.tsv"
    _write_report(report, ["PASS\twbcan-001\tonly check\t1\t1\n"])

    with pytest.raises(MODULE.ReportError, match="at least 2 checks"):
        MODULE.validate_report(report, minimum_checks=2)
