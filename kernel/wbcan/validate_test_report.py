#!/usr/bin/env python3
"""Validate the machine-readable report emitted by test_wbcan.sh."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

EXPECTED_FIELDS = ("result", "test_id", "name", "expected", "actual")


class ReportError(ValueError):
    """A report is malformed or contains a failed assertion."""


def validate_report(path: Path, minimum_checks: int) -> int:
    if not path.is_file():
        raise ReportError(f"report does not exist: {path}")

    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if tuple(reader.fieldnames or ()) != EXPECTED_FIELDS:
            raise ReportError(
                f"header must be tab-separated {EXPECTED_FIELDS!r}; got {reader.fieldnames!r}"
            )

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
        if row["result"] == "FAIL":
            failures.append(f"{test_id} ({row['name']})")

    if failures:
        raise ReportError("failed checks: " + ", ".join(failures))

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
