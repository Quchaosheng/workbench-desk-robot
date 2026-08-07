import json
import sys
from pathlib import Path

from _paths import ROOT

REQUIRED_FIELDS = {
    "issue",
    "human_owner",
    "objective",
    "allowed_paths",
    "read_only_paths",
    "forbidden",
    "acceptance",
    "commands",
    "evidence",
    "stop_conditions",
}


def main() -> int:
    packet_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs/task_packets/example-001-world-reducer.json"
    payload = json.loads(packet_path.read_text(encoding="utf-8"))
    missing = REQUIRED_FIELDS.difference(payload)
    if missing:
        raise RuntimeError(f"Task Packet missing: {', '.join(sorted(missing))}")
    if not payload["allowed_paths"] or not payload["acceptance"] or not payload["commands"]:
        raise RuntimeError("Task Packet has an empty execution boundary")
    print(f"Task Packet validation passed: {packet_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
