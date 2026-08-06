#!/usr/bin/env python3
"""Run reproducible scenario evaluations without confusing fixtures for evidence."""

import argparse
import json
import os
import re
import shlex
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from _paths import enable_local_packages

enable_local_packages()

from pydantic import ValidationError
from workbench_contracts import ScenarioManifest

SAFE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
EVENT_TYPES = {
    "action_request",
    "action_result",
    "emotion",
    "fault",
    "observation",
    "policy_violation",
    "task_accepted",
    "task_graph",
    "task_terminal",
    "verification",
}
VERIFICATION_STATUSES = {"confirmed", "insufficient_evidence", "refuted"}
MAX_EVENT_LOG_BYTES = 10 * 1024 * 1024
MAX_EVENTS_PER_RUN = 10_000
TIMESTAMP_WINDOW_SECONDS = 365 * 24 * 60 * 60


class EvaluationInputError(ValueError):
    """Raised before execution when an evaluation input is unsafe or ambiguous."""


def validate_label(value: str, field: str) -> str:
    if not isinstance(value, str) or not SAFE_LABEL.fullmatch(value):
        raise EvaluationInputError(f"{field} must be a filesystem-safe label: {value!r}")
    return value


def load_scenario_manifests(paths: list[Path]) -> list[tuple[Path, dict[str, Any]]]:
    manifests: list[tuple[Path, dict[str, Any]]] = []
    seen_ids: dict[str, Path] = {}
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            ScenarioManifest.model_validate(payload, strict=True)
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
            raise EvaluationInputError(f"invalid scenario manifest {path}: {exc}") from exc
        scenario_id = validate_label(payload["scenario_id"], "scenario_id")
        if scenario_id in seen_ids:
            raise EvaluationInputError(f"duplicate scenario_id {scenario_id!r} in {seen_ids[scenario_id]} and {path}")
        seen_ids[scenario_id] = path
        manifests.append((path, payload))
    return manifests


def git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text("".join(f"{json.dumps(event, sort_keys=True)}\n" for event in events), encoding="utf-8")
    temporary.replace(path)


def scripted_events(version: str, manifest: dict[str, Any], commit: str, seed_base: int) -> list[dict[str, Any]]:
    """Produce deterministic contract-shaped fixtures for pipeline and UI tests only."""
    scenario_id = manifest["scenario_id"]
    run_id = f"{version}--{scenario_id}"
    effective_seed = seed_base + manifest["seed"]
    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=effective_seed % TIMESTAMP_WINDOW_SECONDS)
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


def validate_event_log(
    path: Path,
    run_id: str,
    *,
    scenario_id: str | None = None,
    seed: int | None = None,
    commit: str | None = None,
) -> list[dict[str, Any]]:
    try:
        if path.stat().st_size > MAX_EVENT_LOG_BYTES:
            raise RuntimeError(f"event log exceeds {MAX_EVENT_LOG_BYTES} bytes: {path}")
        events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except RuntimeError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"runner produced an unreadable JSONL event log: {path}") from exc
    if not events:
        raise RuntimeError(f"runner produced an empty event log: {path}")
    if len(events) > MAX_EVENTS_PER_RUN:
        raise RuntimeError(f"runner produced more than {MAX_EVENTS_PER_RUN} events: {path}")
    if any(not isinstance(event, dict) for event in events):
        raise RuntimeError(f"event log contains a non-object event: {path}")
    sequences = [event.get("sequence_no") for event in events]
    if any(type(sequence) is not int for sequence in sequences) or sequences != list(range(len(events))):
        raise RuntimeError(f"non-contiguous sequence_no values in {path}: {sequences}")
    if any(event.get("run_id") != run_id for event in events):
        raise RuntimeError(f"run_id drift in {path}")
    event_ids = [event.get("event_id") for event in events]
    if any(not isinstance(event_id, str) or not event_id for event_id in event_ids):
        raise RuntimeError(f"missing event_id in {path}")
    if len(event_ids) != len(set(event_ids)):
        raise RuntimeError(f"duplicate event_id in {path}")
    for event in events:
        event_type = event.get("event_type")
        if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
            raise RuntimeError(f"unknown event_type in {path}: {event_type!r}")
        if not isinstance(event.get("occurred_at"), str) or not event["occurred_at"]:
            raise RuntimeError(f"missing occurred_at in {path}")
        if not isinstance(event.get("payload"), dict):
            raise RuntimeError(f"event payload is not an object in {path}")
        evidence_refs = event.get("evidence_refs", [])
        if not isinstance(evidence_refs, list) or any(not isinstance(ref, str) for ref in evidence_refs):
            raise RuntimeError(f"event evidence_refs is not a string list in {path}")
        evaluation = event.get("evaluation")
        if not isinstance(evaluation, dict):
            raise RuntimeError(f"event is missing evaluation metadata in {path}")
        if not isinstance(evaluation.get("commit"), str) or not evaluation["commit"]:
            raise RuntimeError(f"event is missing evaluation commit in {path}")
        if not isinstance(evaluation.get("scenario_id"), str) or not evaluation["scenario_id"]:
            raise RuntimeError(f"event is missing evaluation scenario_id in {path}")
        if type(evaluation.get("seed")) is not int:
            raise RuntimeError(f"event is missing integer evaluation seed in {path}")
        if scenario_id is not None and evaluation["scenario_id"] != scenario_id:
            raise RuntimeError(f"evaluation scenario_id drift in {path}")
        if seed is not None and evaluation["seed"] != seed:
            raise RuntimeError(f"evaluation seed drift in {path}")
        if commit is not None and evaluation["commit"] != commit:
            raise RuntimeError(f"evaluation commit drift in {path}")
    verifications = [event for event in events if event.get("event_type") == "verification"]
    if not verifications:
        raise RuntimeError(f"event log contains no verification result: {path}")
    if any(
        not isinstance(event["payload"].get("status"), str)
        or event["payload"].get("status") not in VERIFICATION_STATUSES
        for event in verifications
    ):
        raise RuntimeError(f"verification contains an unknown status in {path}")
    for event in verifications:
        event_evidence = event.get("evidence_refs")
        payload_evidence = event["payload"].get("evidence_refs")
        if (
            not isinstance(event_evidence, list)
            or not event_evidence
            or any(not isinstance(reference, str) for reference in event_evidence)
            or not isinstance(payload_evidence, list)
            or not payload_evidence
            or any(not isinstance(reference, str) for reference in payload_evidence)
        ):
            raise RuntimeError(f"verification without evidence_refs in {path}")
    terminals = [event for event in events if event.get("event_type") == "task_terminal"]
    if terminals and terminals[-1]["payload"].get("status") != verifications[-1]["payload"].get("status"):
        raise RuntimeError(f"terminal status disagrees with final verification in {path}")
    return events


def run_external(command_template: str, manifest_path: Path, output_path: Path, seed: int, version: str) -> None:
    substitutions = {
        "manifest": str(manifest_path.resolve()),
        "output": str(output_path.resolve()),
        "seed": str(seed),
        "version": version,
    }
    try:
        command = command_template.format(**substitutions)
    except (KeyError, ValueError) as exc:
        raise EvaluationInputError(f"invalid runner command template: {exc}") from exc
    try:
        result = subprocess.run(
            shlex.split(command, posix=os.name != "nt"),
            capture_output=True,
            check=False,
            text=True,
            timeout=900,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("external runner timed out after 900 seconds") from exc
    except OSError as exc:
        raise RuntimeError(f"external runner could not start: {exc}") from exc
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
        raise EvaluationInputError("--runner-command is required for the external runner")
    versions = [version.strip() for version in args.versions.split(",") if version.strip()]
    scenarios = sorted(args.scenarios)
    if not versions or not scenarios:
        raise EvaluationInputError("at least one version and scenario are required")
    for version in versions:
        validate_label(version, "version")
    if len(versions) != len(set(versions)):
        raise EvaluationInputError("version labels must be unique")
    manifests = load_scenario_manifests(scenarios)

    commit = git_commit()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    print(f"Running {len(versions)} version(s) x {len(scenarios)} scenario(s) with {args.runner} runner")

    for version in versions:
        version_dir = args.output_dir / version
        version_dir.mkdir(exist_ok=True)
        for scenario_path, manifest in manifests:
            run_id = f"{version}--{manifest['scenario_id']}"
            output_path = version_dir / f"{manifest['scenario_id']}.jsonl"
            effective_seed = args.seed_base + manifest["seed"]
            if args.runner == "scripted":
                write_jsonl(output_path, scripted_events(version, manifest, commit, args.seed_base))
                events = validate_event_log(
                    output_path,
                    run_id,
                    scenario_id=manifest["scenario_id"],
                    seed=effective_seed,
                    commit=commit,
                )
            else:
                partial_path = output_path.with_name(f".{output_path.name}.partial")
                partial_path.unlink(missing_ok=True)
                try:
                    run_external(args.runner_command, scenario_path, partial_path, effective_seed, version)
                    events = validate_event_log(
                        partial_path,
                        run_id,
                        scenario_id=manifest["scenario_id"],
                        seed=effective_seed,
                        commit=commit,
                    )
                    partial_path.replace(output_path)
                finally:
                    partial_path.unlink(missing_ok=True)
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
                    "release_eligible": args.runner == "external" and commit != "unknown",
                }
            )
            print(f"  {run_id}: {summaries[-1]['verification_status']}")

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "commit": commit,
        "runner": args.runner,
        "release_eligible": args.runner == "external" and commit != "unknown",
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
