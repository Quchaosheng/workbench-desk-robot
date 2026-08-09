#!/usr/bin/env python3
"""Compute stage P50/P95 from simulation or attested hardware JSONL logs."""

import argparse
import json
from pathlib import Path

from performance_tools import load_telemetry, summarize_telemetry, validate_hardware_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze unified Workbench-1 stage telemetry")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--hardware-evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records, paths = load_telemetry(args.inputs)
    hardware_evidence = validate_hardware_evidence(paths, args.hardware_evidence)
    report = summarize_telemetry(records, hardware_evidence=hardware_evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
