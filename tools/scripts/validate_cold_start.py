#!/usr/bin/env python3
"""Validate the three-person clean-machine cold-start evidence table."""

import argparse
import json
from pathlib import Path


def validate(payload: object) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("participants"), list):
        raise RuntimeError("cold-start evidence must contain a participants list")
    participants = payload["participants"]
    if len(participants) < 3:
        raise RuntimeError("at least three participant records are required")
    ids = [participant.get("participant_id") for participant in participants if isinstance(participant, dict)]
    if len(ids) != len(participants) or any(not isinstance(value, str) or not value for value in ids):
        raise RuntimeError("every participant needs a non-empty participant_id")
    if len(ids) != len(set(ids)):
        raise RuntimeError("participant_id values must be unique")
    for participant in participants:
        required = {
            "participant_id",
            "os",
            "docker_version",
            "started_at",
            "first_ready_at",
            "elapsed_minutes",
            "result",
        }
        if not required.issubset(participant):
            raise RuntimeError(f"participant record is missing fields: {participant.get('participant_id')}")
        if participant["result"] not in {"pass", "fail"}:
            raise RuntimeError(f"invalid participant result: {participant['participant_id']}")
        if type(participant["elapsed_minutes"]) not in (int, float) or participant["elapsed_minutes"] < 0:
            raise RuntimeError(f"invalid elapsed_minutes: {participant['participant_id']}")
        if participant["result"] == "pass" and participant["elapsed_minutes"] > 60:
            raise RuntimeError(f"passing participant exceeded 60 minutes: {participant['participant_id']}")
    passed = sum(participant["result"] == "pass" for participant in participants)
    return {"participant_count": len(participants), "pass_count": passed, "accepted": passed >= 2}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate external cold-start records")
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    summary = validate(json.loads(args.evidence.read_text(encoding="utf-8")))
    print(json.dumps(summary, indent=2))
    if not summary["accepted"]:
        raise SystemExit("cold-start acceptance requires at least two passes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
