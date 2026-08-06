#!/usr/bin/env python3
"""Extract reproducible metrics from one version's JSON Lines event logs."""

import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

ALLOWED_ACTIONS = {"ask_confirm", "express", "grasp", "observe", "place", "stop"}


def load_runs(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    runs: dict[str, list[dict[str, Any]]] = {}
    for log_file in sorted(run_dir.glob("*.jsonl")):
        events = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not events:
            continue
        run_id = str(events[0].get("run_id", ""))
        if not run_id:
            raise RuntimeError(f"event log has no run_id: {log_file}")
        runs[run_id] = sorted(events, key=lambda event: event.get("sequence_no", -1))
    return runs


def verification_statuses(events: list[dict[str, Any]]) -> list[str]:
    return [
        str(event.get("payload", {}).get("status")) for event in events if event.get("event_type") == "verification"
    ]


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def durations(runs: dict[str, list[dict[str, Any]]]) -> list[float]:
    result = []
    for events in runs.values():
        if len(events) < 2:
            continue
        try:
            start = datetime.fromisoformat(events[0]["occurred_at"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(events[-1]["occurred_at"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        result.append((end - start).total_seconds())
    return result


def replay_digest(events: list[dict[str, Any]]) -> str:
    state = {
        "run_id": events[0].get("run_id") if events else None,
        "event_ids": [],
        "last_action": None,
        "verification_status": None,
        "evidence_refs": [],
    }
    for event in sorted(events, key=lambda item: item.get("sequence_no", -1)):
        state["event_ids"].append(event.get("event_id"))
        if event.get("event_type") == "action_result":
            state["last_action"] = event.get("payload")
        if event.get("event_type") == "verification":
            state["verification_status"] = event.get("payload", {}).get("status")
        state["evidence_refs"].extend(event.get("evidence_refs", []))
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def audit_false_completions(
    runs: dict[str, list[dict[str, Any]]], audit_path: Path | None
) -> tuple[int | None, bool, str | None]:
    if audit_path is None:
        return None, False, None
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    decisions = audit.get("runs", {})
    missing = sorted(set(runs) - set(decisions))
    if missing:
        raise RuntimeError(f"human audit is missing {len(missing)} run(s)")
    false_completions = 0
    for run_id, events in runs.items():
        statuses = verification_statuses(events)
        claimed_complete = bool(statuses and statuses[-1] == "confirmed")
        oracle_status = decisions[run_id].get("oracle_status")
        if claimed_complete and oracle_status != "confirmed":
            false_completions += 1
    return false_completions, True, audit.get("reviewed_by")


def collect(run_dir: Path, audit_path: Path | None = None) -> dict[str, Any]:
    runs = load_runs(run_dir)
    if not runs:
        raise RuntimeError(f"no JSON Lines event logs found in {run_dir}")
    events = [event for run in runs.values() for event in run]
    final_statuses = [verification_statuses(run)[-1] for run in runs.values() if verification_statuses(run)]
    verified = sum(status == "confirmed" for status in final_statuses)
    task_durations = durations(runs)
    action_requests = [event for event in events if event.get("event_type") == "action_request"]
    observations = [event for event in events if event.get("event_type") == "observation"]
    verifications = [event for event in events if event.get("event_type") == "verification"]
    plans = [event for event in events if event.get("event_type") == "task_graph"]

    recoverable = [run for run in runs.values() if "refuted" in verification_statuses(run)[:-1]]
    recovered = sum(verification_statuses(run)[-1] == "confirmed" for run in recoverable)
    valid_replays = sum(
        [event.get("sequence_no") for event in run] == list(range(len(run)))
        and all(event.get("run_id") == run_id for event in run)
        for run_id, run in runs.items()
    )
    stable_hashes = sum(replay_digest(run) == replay_digest(list(reversed(run))) for run in runs.values())
    false_completions, audit_complete, reviewed_by = audit_false_completions(runs, audit_path)

    summary_path = run_dir.parent / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
    return {
        "false_completion_count": false_completions,
        "false_completion_reviewed": audit_complete,
        "false_completion_reviewed_by": reviewed_by,
        "collision_count": sum(
            event.get("event_type") == "fault" and event.get("payload", {}).get("fault_type") == "collision"
            for event in events
        ),
        "policy_violation_count": sum(event.get("event_type") == "policy_violation" for event in events),
        "vtcr": verified / len(final_statuses) if final_statuses else 0.0,
        "task_duration_p50_s": percentile(task_durations, 0.5),
        "task_duration_p95_s": percentile(task_durations, 0.95),
        "recovery_rate": recovered / len(recoverable) if recoverable else None,
        "tool_call_validity": (
            sum(event.get("payload", {}).get("action_type") in ALLOWED_ACTIONS for event in action_requests)
            / len(action_requests)
            if action_requests
            else 1.0
        ),
        "local_planning_coverage": (
            sum(event.get("payload", {}).get("model_route") in {"local", "template"} for event in plans) / len(plans)
            if plans
            else 0.0
        ),
        "observation_completeness": (
            sum(
                all(
                    field in event.get("payload", {})
                    for field in ("observation_id", "run_id", "entity_id", "pose", "confidence")
                )
                for event in observations
            )
            / len(observations)
            if observations
            else 1.0
        ),
        "evidence_coverage": (
            sum(bool(event.get("payload", {}).get("evidence_refs")) for event in verifications) / len(verifications)
            if verifications
            else 0.0
        ),
        "state_hash_consistency": stable_hashes / len(runs),
        "replay_success_rate": valid_replays / len(runs),
        "run_count": len(runs),
        "total_events": len(events),
        "run_dir": str(run_dir),
        "runner": summary.get("runner", "unknown"),
        "release_eligible": bool(summary.get("release_eligible", False)) and audit_complete,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract metrics from event logs")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("metrics.json"))
    parser.add_argument("--human-audit", type=Path)
    args = parser.parse_args()
    metrics = collect(args.run_dir, args.human_audit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    print(f"metrics written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
