#!/usr/bin/env python3
"""Run reproducible scenario evaluations without confusing fixtures for evidence."""

import argparse
import json
import os
import shlex
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        check=False,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    path.write_text("".join(f"{json.dumps(event, sort_keys=True)}\n" for event in events), encoding="utf-8")


def scripted_events(version: str, manifest: dict[str, Any], commit: str, seed_base: int) -> list[dict[str, Any]]:
    """Produce deterministic contract-shaped fixtures for pipeline and UI tests only."""
    scenario_id = manifest["scenario_id"]
    run_id = f"{version}--{scenario_id}"
    effective_seed = seed_base + manifest["seed"]
    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=effective_seed)
    events: list[dict[str, Any]] = []

    def append(event_type: str, payload: dict[str, Any], evidence_refs: list[str] | None = None) -> None:
        sequence_no = len(events)
        events.append(
            {
                "event_id": f"{run_id}-evt-{sequence_no:03d}",
                "run_id": run_id,
                "sequence_no": sequence_no,
                "event_type": event_type,
                "occurred_at": (start + timedelta(seconds=sequence_no * 4)).isoformat().replace("+00:00", "Z"),
                "payload": payload,
                "evidence_refs": evidence_refs or [],
                "evaluation": {
                    "commit": commit,
                    "scenario_id": scenario_id,
                    "seed": effective_seed,
                    "runner": "scripted",
                },
            }
        )

    append(
        "task_accepted",
        {
            "task_id": manifest["task_id"],
            "goal": "Place the red block in the tray",
            "version": version,
        },
    )
    append(
        "task_graph",
        {
            "task_id": manifest["task_id"],
            "planner": "template-v1",
            "model_route": "template",
            "actions": ["observe", "grasp", "place"],
        },
    )
    append(
        "observation",
        {
            "observation_id": f"{run_id}-obs-001",
            "run_id": run_id,
            "entity_id": "red_block",
            "entity_type": "block",
            "pose": {"frame_id": "world", "position": {"x": 0.08, "y": -0.03, "z": 0.02}},
            "confidence": 0.42 if manifest["fault_type"] in {"occlusion", "camera_dropout"} else 0.97,
        },
        [f"frame://{run_id}/001"],
    )
    append("action_request", {"action_id": "act-001", "action_type": "grasp", "target_id": "red_block"})

    fault_type = manifest["fault_type"]
    if fault_type in {"grasp_failure", "actuator_timeout"}:
        append(
            "action_result",
            {"action_id": "act-001", "status": "failed", "detail": fault_type},
            [f"motion-log://{run_id}/attempt-1"],
        )
        append(
            "verification",
            {
                "verification_id": f"{run_id}-verify-001",
                "task_id": manifest["task_id"],
                "claim": "red_block in tray",
                "status": "refuted",
                "reason_code": "goal_not_satisfied",
                "recovery_hint": "retry_action",
                "evidence_refs": [f"motion-log://{run_id}/attempt-1"],
            },
            [f"motion-log://{run_id}/attempt-1"],
        )
        append("action_request", {"action_id": "act-002", "action_type": "grasp", "target_id": "red_block"})
        append(
            "action_result",
            {
                "action_id": "act-002",
                "status": "succeeded",
                "entity_id": "red_block",
                "resulting_location": "in:tray",
            },
            [f"motion-log://{run_id}/attempt-2"],
        )
        status = "confirmed"
        reason_code = "goal_satisfied"
        evidence = [f"frame://{run_id}/recovery", f"motion-log://{run_id}/attempt-2"]
    elif fault_type in {"occlusion", "camera_dropout", "stale_observation"}:
        append(
            "action_result",
            {"action_id": "act-001", "status": "succeeded", "detail": "dispatch is not completion"},
            [f"motion-log://{run_id}/attempt-1"],
        )
        status = "insufficient_evidence"
        reason_code = "stale_observation" if fault_type == "stale_observation" else "confidence_below_threshold"
        evidence = [f"frame://{run_id}/001"]
    elif fault_type == "moving_target":
        append(
            "action_result",
            {"action_id": "act-001", "status": "failed", "detail": "target moved"},
            [f"motion-log://{run_id}/attempt-1"],
        )
        status = "refuted"
        reason_code = "goal_not_satisfied"
        evidence = [f"frame://{run_id}/moved", f"motion-log://{run_id}/attempt-1"]
    else:
        append(
            "action_result",
            {
                "action_id": "act-001",
                "status": "succeeded",
                "entity_id": "red_block",
                "resulting_location": "in:tray",
            },
            [f"motion-log://{run_id}/attempt-1"],
        )
        status = "confirmed"
        reason_code = "goal_satisfied"
        evidence = [f"frame://{run_id}/final", f"motion-log://{run_id}/attempt-1"]

    missing_evidence = ["fresh_camera_frame"] if status == "insufficient_evidence" else []
    append(
        "verification",
        {
            "verification_id": f"{run_id}-verify-final",
            "task_id": manifest["task_id"],
            "claim": "red_block in tray",
            "status": status,
            "reason_code": reason_code,
            "recovery_hint": "re_observe" if status == "insufficient_evidence" else "none",
            "missing_evidence": missing_evidence,
            "evidence_refs": evidence,
        },
        evidence,
    )
    append("task_terminal", {"task_id": manifest["task_id"], "status": status}, evidence)
    return events


def validate_event_log(path: Path, run_id: str) -> list[dict[str, Any]]:
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not events:
        raise RuntimeError(f"runner produced an empty event log: {path}")
    sequences = [event.get("sequence_no") for event in events]
    if sequences != list(range(len(events))):
        raise RuntimeError(f"non-contiguous sequence_no values in {path}: {sequences}")
    if any(event.get("run_id") != run_id for event in events):
        raise RuntimeError(f"run_id drift in {path}")
    verifications = [event for event in events if event.get("event_type") == "verification"]
    if any(not event.get("payload", {}).get("evidence_refs") for event in verifications):
        raise RuntimeError(f"verification without evidence_refs in {path}")
    return events


def run_external(command_template: str, manifest_path: Path, output_path: Path, seed: int, version: str) -> None:
    substitutions = {
        "manifest": str(manifest_path.resolve()),
        "output": str(output_path.resolve()),
        "seed": str(seed),
        "version": version,
    }
    command = command_template.format(**substitutions)
    result = subprocess.run(
        shlex.split(command, posix=os.name != "nt"),
        capture_output=True,
        check=False,
        text=True,
        timeout=900,
    )
    if result.returncode != 0:
        raise RuntimeError(f"external runner failed ({result.returncode}): {result.stderr.strip()}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run reproducible Workbench-1 evaluations")
    parser.add_argument("--versions", required=True, help="Comma-separated version labels")
    parser.add_argument("--scenarios", nargs="+", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed-base", type=int, default=1000)
    parser.add_argument("--runner", choices=("scripted", "external"), default="scripted")
    parser.add_argument(
        "--runner-command", help="External command template with {manifest}, {output}, {seed}, {version}"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.runner == "external" and not args.runner_command:
        raise ValueError("--runner-command is required for the external runner")
    versions = [version.strip() for version in args.versions.split(",") if version.strip()]
    scenarios = sorted(args.scenarios)
    if not versions or not scenarios:
        raise ValueError("at least one version and scenario are required")

    commit = git_commit()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    print(f"Running {len(versions)} version(s) x {len(scenarios)} scenario(s) with {args.runner} runner")

    for version in versions:
        version_dir = args.output_dir / version
        version_dir.mkdir(exist_ok=True)
        for scenario_path in scenarios:
            manifest = json.loads(scenario_path.read_text(encoding="utf-8"))
            run_id = f"{version}--{manifest['scenario_id']}"
            output_path = version_dir / f"{manifest['scenario_id']}.jsonl"
            effective_seed = args.seed_base + manifest["seed"]
            if args.runner == "scripted":
                write_jsonl(output_path, scripted_events(version, manifest, commit, args.seed_base))
            else:
                run_external(args.runner_command, scenario_path, output_path, effective_seed, version)
            events = validate_event_log(output_path, run_id)
            final_verification = [event for event in events if event["event_type"] == "verification"][-1]
            summaries.append(
                {
                    "run_id": run_id,
                    "version": version,
                    "scenario_id": manifest["scenario_id"],
                    "seed": effective_seed,
                    "commit": commit,
                    "runner": args.runner,
                    "event_log": str(output_path),
                    "verification_status": final_verification["payload"]["status"],
                    "release_eligible": args.runner == "external",
                }
            )
            print(f"  {run_id}: {summaries[-1]['verification_status']}")

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "commit": commit,
        "runner": args.runner,
        "release_eligible": args.runner == "external",
        "run_count": len(summaries),
        "runs": summaries,
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if args.runner == "scripted":
        print("Scripted fixtures completed. These runs test the pipeline and are not release evidence.")
    print(f"Wrote {len(summaries)} validated event logs to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
