#!/usr/bin/env python3
"""Append one validated hardware-evidence record."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from evidence import register, sha256

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "hardware" / "validation"


def rows(name: str) -> list[dict[str, str]]:
    with (PACKAGE / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description="Register hardware-validation evidence")
    parser.add_argument("--evidence-id", required=True)
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--unit-id", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--captured-at", required=True, help="UTC ISO-8601 timestamp")
    parser.add_argument("--evidence-kind", choices=("simulation", "bench", "physical"), required=True)
    parser.add_argument("--instrument-ref", action="append", required=True)
    parser.add_argument("--calibration-ref", action="append", required=True)
    parser.add_argument("--raw-file", action="append", type=Path, required=True)
    parser.add_argument("--result", choices=("PASS", "FAIL", "HOLD"), required=True)
    parser.add_argument("--register", type=Path, default=PACKAGE / "evidence-register.jsonl")
    args = parser.parse_args()

    units = {
        row["unit_id"]: (row["hardware_revision"], row["firmware_hash"])
        for row in rows("first-batch-acceptance.csv")
        if row["hardware_revision"] != "UNASSIGNED" and row["firmware_hash"] != "UNASSIGNED"
    }
    raw_files = {}
    for raw_file in args.raw_file:
        resolved = raw_file.resolve()
        try:
            relative = resolved.relative_to(ROOT.resolve())
        except ValueError as exc:
            raise RuntimeError(f"raw evidence must be inside the repository: {raw_file}") from exc
        raw_files[relative.as_posix()] = sha256(resolved)
    hardware_revision, config_hash = units.get(args.unit_id, ("", ""))
    record = {
        "evidence_id": args.evidence_id,
        "scenario_id": args.scenario_id,
        "unit_id": args.unit_id,
        "hardware_revision": hardware_revision,
        "config_hash": config_hash,
        "operator": args.operator,
        "reviewer": args.reviewer,
        "captured_at": args.captured_at,
        "evidence_kind": args.evidence_kind,
        "instrument_refs": args.instrument_ref,
        "calibration_refs": args.calibration_ref,
        "raw_files": raw_files,
        "result": args.result,
    }
    register(
        args.register,
        record,
        root=ROOT,
        scenarios={row["scenario_id"] for row in rows("fault-scenarios.csv")},
        units=units,
    )
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
