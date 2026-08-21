#!/usr/bin/env python3
"""Create an operator-attested manifest binding hardware logs to their hashes."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from performance_tools import hardware_log_hashes


def main() -> int:
    parser = argparse.ArgumentParser(description="Register real-hardware performance evidence")
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--hardware-id", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in args.logs:
        if not path.is_file():
            raise RuntimeError(f"hardware log does not exist: {path}")
    manifest = {
        "evidence_kind": "operator_attested_real_hardware",
        "hardware_id": args.hardware_id,
        "operator": args.operator,
        "captured_at": datetime.now(UTC).isoformat(),
        "logs": hardware_log_hashes(args.logs),
        "attestation": "The named operator confirms these logs were captured from the identified physical system.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
