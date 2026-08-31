#!/usr/bin/env python3
"""Extract reproducible metrics from one version's JSON Lines event logs."""

import argparse
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from workbench_contracts import WorldEvent
from workbench_world_model import create_world_state_snapshot

ALLOWED_ACTIONS = {"ask_confirm", "express", "grasp", "observe", "place", "stop"}


def load_runs(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    runs: dict[str, list[dict[str, Any]]] = {}
    for log_file in sorted(run_dir.glob("*.jsonl")):
        events: list[dict[str, Any]] = []
        for line_number, line in enumerate(log_file.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise RuntimeError(f"unreadable JSONL event at {log_file}:{line_number}") from error
            if type(event) is not dict:
                raise RuntimeError(f"WorldEvent at {log_file}:{line_number} must be a JSON object")
            events.append(event)
        if not events:
            continue
        run_id = events[0].get("run_id")
        if type(run_id) is not str or not run_id.strip():
            raise RuntimeError(f"event log has no run_id: {log_file}")
        if run_id in runs:
            raise RuntimeError(f"run_id {run_id!r} is owned by more than one event log")
        runs[run_id] = events
    return runs


def _canonical_replay(run_id: str, events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str, str]:
    typed_events: list[WorldEvent] = []
    try:
        for event in events:
            encoded = json.dumps(event, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
            typed_events.append(WorldEvent.model_validate_json(encoded))
        forward = create_world_state_snapshot(run_id, typed_events)
        reverse = create_world_state_snapshot(run_id, list(reversed(typed_events)))
    except (TypeError, UnicodeError, ValueError) as error:
        raise RuntimeError(f"canonical replay failed for run_id {run_id!r}: {error}") from error
    canonical_events = [
        event.model_dump(mode="json") for event in sorted(typed_events, key=lambda item: item.sequence_no)
    ]
    return canonical_events, forward.state_hash, reverse.state_hash


def canonical_replay_hash(events: list[dict[str, Any]]) -> str:
    """Return #47's canonical WorldState hash for one untrusted event stream."""
    if not events:
        raise RuntimeError("canonical replay requires a non-empty event stream")
    run_id = events[0].get("run_id")
    if type(run_id) is not str or not run_id.strip():
        raise RuntimeError("canonical replay requires a non-empty run_id")
    _, state_hash, _ = _canonical_replay(run_id, events)
    return state_hash


def verification_statuses(events: list[dict[str, Any]]) -> list[str]:
    return [
        str(event.get("payload", {}).get("status")) for event in events if event.get("event_type") == "verification"
    ]


def task_id(events: list[dict[str, Any]]) -> str:
    accepted = next((event for event in events if event.get("event_type") == "task_accepted"), {})
    return str(accepted.get("payload", {}).get("task_id", "unknown"))


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
    untrusted_runs = load_runs(run_dir)
    if not untrusted_runs:
        raise RuntimeError(f"no JSON Lines event logs found in {run_dir}")
    replayed = {run_id: _canonical_replay(run_id, run) for run_id, run in untrusted_runs.items()}
    runs = {run_id: result[0] for run_id, result in replayed.items()}
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
    valid_replays = len(replayed)
    stable_hashes = sum(forward_hash == reverse_hash for _, forward_hash, reverse_hash in replayed.values())
    false_completions, audit_complete, reviewed_by = audit_false_completions(runs, audit_path)
    run_task_ids = {run_id: task_id(run) for run_id, run in runs.items()}
    task_family_distribution = Counter(run_task_ids.values())
    task_family_vtcr = {}
    for family, family_run_count in sorted(task_family_distribution.items()):
        family_runs = [run for run_id, run in runs.items() if run_task_ids[run_id] == family]
        family_verified = sum(
            bool(verification_statuses(run)) and verification_statuses(run)[-1] == "confirmed" for run in family_runs
        )
        task_family_vtcr[family] = family_verified / family_run_count
    observed_entities = [
        len(
            {
                event.get("payload", {}).get("entity_id")
                for event in run
                if event.get("event_type") == "observation" and event.get("payload", {}).get("entity_id")
            }
        )
        for run in runs.values()
    ]
    final_verifications = [
        [event for event in run if event.get("event_type") == "verification"][-1]
        for run in runs.values()
        if any(event.get("event_type") == "verification" for event in run)
    ]
    required_condition_count = 0
    evaluated_condition_count = 0
    for event in final_verifications:
        payload = event.get("payload", {})
        required = payload.get("required_conditions", [])
        evaluated = payload.get("evaluated_conditions", [])
        required_set = set(required) if isinstance(required, list) else set()
        evaluated_set = set(evaluated) if isinstance(evaluated, list) else set()
        required_condition_count += len(required_set)
        evaluated_condition_count += len(required_set & evaluated_set)

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
        "task_family_count": len(task_family_distribution),
        "task_family_distribution": dict(sorted(task_family_distribution.items())),
        "task_family_vtcr": task_family_vtcr,
        "complex_task_rate": sum(family != "task-place-red-block" for family in run_task_ids.values()) / len(runs),
        "mean_observed_entities": sum(observed_entities) / len(observed_entities) if observed_entities else 0.0,
        "goal_condition_coverage": (
            evaluated_condition_count / required_condition_count if required_condition_count else 0.0
        ),
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
