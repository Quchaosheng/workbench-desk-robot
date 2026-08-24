#!/usr/bin/env python3
"""Validate the machine-readable report emitted by test_wbcan.sh."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

EXPECTED_FIELDS = ("result", "test_id", "name", "expected", "actual")
SUITE_PATH = Path(__file__).with_name("test_wbcan.sh")


class ReportError(ValueError):
    """A report is malformed or contains a failed assertion."""


def _test_id(name: str) -> str:
    slug = "".join(
        character for character in name.lower().replace(" ", "_") if character.isalnum() or character in "_-"
    )
    return f"wbcan-{slug}"


def expected_checks(path: Path = SUITE_PATH) -> dict[str, str]:
    names = re.findall(r'^\s*check "([^"]+)"', path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    checks = {_test_id(name): name for name in names}
    if len(checks) != len(set(names)):
        raise ReportError("wbcan suite contains duplicate or colliding check identities")
    return checks


def validate_report(
    path: Path,
    minimum_checks: int,
    required_test_ids: set[str] | frozenset[str] | None = None,
) -> int:
    if not path.is_file():
        raise ReportError(f"report does not exist: {path}")

    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if tuple(reader.fieldnames or ()) != EXPECTED_FIELDS:
            raise ReportError(f"header must be tab-separated {EXPECTED_FIELDS!r}; got {reader.fieldnames!r}")

        rows = list(reader)

    if len(rows) < minimum_checks:
        raise ReportError(f"expected at least {minimum_checks} checks; got {len(rows)}")

    seen: set[str] = set()
    failures: list[str] = []
    for line_no, row in enumerate(rows, start=2):
        if None in row:
            raise ReportError(f"line {line_no}: unexpected extra report fields")
        if any(value is None or value == "" for value in row.values()):
            raise ReportError(f"line {line_no}: all report fields are required")
        test_id = row["test_id"]
        if test_id in seen:
            raise ReportError(f"line {line_no}: duplicate test_id {test_id!r}")
        seen.add(test_id)
        if row["result"] not in {"PASS", "FAIL"}:
            raise ReportError(f"line {line_no}: invalid result {row['result']!r}")
        if test_id != _test_id(row["name"]):
            raise ReportError(f"line {line_no}: test_id does not match check name")
        if row["result"] == "PASS" and row["expected"] != row["actual"]:
            failures.append(f"{test_id} ({row['name']}: PASS contradicts expected/actual)")
        elif row["result"] == "FAIL":
            failures.append(f"{test_id} ({row['name']})")

    if failures:
        raise ReportError("failed checks: " + ", ".join(failures))

    required = set(expected_checks()) if required_test_ids is None else set(required_test_ids)
    missing = sorted(required - seen)
    unexpected = sorted(seen - required)
    if missing or unexpected:
        raise ReportError(f"test_id set mismatch: missing={missing}; unexpected={unexpected}")

    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--min-checks", type=int, default=60)
    args = parser.parse_args()
    if args.min_checks < 1:
        parser.error("--min-checks must be positive")

    try:
        count = validate_report(args.report, args.min_checks)
    except ReportError as exc:
        parser.error(str(exc))
    print(f"wbcan test report valid: {count} checks, all PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
