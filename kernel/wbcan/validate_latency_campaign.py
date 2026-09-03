#!/usr/bin/env python3
"""Build and validate repeated idle-versus-load wbcan latency evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_latency as latency

SCHEMA_VERSION = "wbcan-latency-campaign-v1"
SCOPE = "virtual-wbcan-userspace-comparison"
MIN_CAMPAIGN_REPETITIONS = 3
THRESHOLD_POLICY = "observational-only-no-latency-pass-threshold"
COMPARABLE_FIELDS = (
    "interface",
    "commit",
    "kernel",
    "kernel_config_sha256",
    "preemption_model",
    "cpu_count",
    "cpu_affinity",
    "clock",
    "warmup_count",
    "sample_count",
    "message_size",
    "can_id",
    "deadline_ns",
    "repetition_count",
    "run_budget",
)
COMPARISON_METRICS = (
    ("latency_p50_ns", "latency", "p50_ns"),
    ("latency_p95_ns", "latency", "p95_ns"),
    ("latency_p99_ns", "latency", "p99_ns"),
    ("latency_max_ns", "latency", "max_ns"),
    ("jitter_ns", "latency", "jitter_ns"),
    ("elapsed_ns", None, "elapsed_ns"),
    ("process_cpu_ns", None, "process_cpu_ns"),
    ("throughput_fps", None, "throughput_fps"),
)
CAMPAIGN_FIELDS = {
    "schema_version",
    "scope",
    "result",
    "threshold_policy",
    "environment",
    "profiles",
    "observed_comparison",
    "claims",
}


def _report_digest(report: dict[str, Any]) -> str:
    return hashlib.sha256(latency.serialized_report(report)).hexdigest()


def _median(envelope: dict[str, Any], section: str | None, field: str) -> int:
    values = envelope[field] if section is None else envelope[section][field]
    return values["nearest_rank_median"]


def observed_comparison(idle: dict[str, Any], controlled: dict[str, Any]) -> dict[str, Any]:
    idle_envelope = idle["observed_envelope"]
    controlled_envelope = controlled["observed_envelope"]
    metrics: dict[str, dict[str, int]] = {}
    for name, section, field in COMPARISON_METRICS:
        idle_value = _median(idle_envelope, section, field)
        controlled_value = _median(controlled_envelope, section, field)
        metrics[name] = {
            "idle_nearest_rank_median": idle_value,
            "controlled_load_nearest_rank_median": controlled_value,
            "signed_delta": controlled_value - idle_value,
        }
    return {
        "method": "same-environment-profile-envelope",
        "interpretation": "informational-only",
        "metrics": metrics,
    }


def _validate_source_reports(idle: dict[str, Any], controlled: dict[str, Any]) -> None:
    latency.validate_report(idle)
    latency.validate_report(controlled)
    if idle.get("result") != "PASS" or controlled.get("result") != "PASS":
        raise ValueError("latency campaign requires passing source reports")
    if idle.get("load_profile") != "idle" or controlled.get("load_profile") != "controlled-load":
        raise ValueError("latency campaign requires idle and controlled-load source reports")
    if min(idle["repetition_count"], controlled["repetition_count"]) < MIN_CAMPAIGN_REPETITIONS:
        raise ValueError(f"latency campaign requires at least {MIN_CAMPAIGN_REPETITIONS} repetitions per profile")
    mismatches = [field for field in COMPARABLE_FIELDS if idle.get(field) != controlled.get(field)]
    if mismatches:
        raise ValueError(f"latency campaign source reports are not comparable: {', '.join(mismatches)}")


def build_campaign(idle: dict[str, Any], controlled: dict[str, Any]) -> dict[str, Any]:
    _validate_source_reports(idle, controlled)
    environment = {field: idle[field] for field in COMPARABLE_FIELDS}
    campaign = {
        "schema_version": SCHEMA_VERSION,
        "scope": SCOPE,
        "result": "PASS",
        "threshold_policy": THRESHOLD_POLICY,
        "environment": environment,
        "profiles": {
            "idle": {"source_sha256": _report_digest(idle), "report": idle},
            "controlled-load": {"source_sha256": _report_digest(controlled), "report": controlled},
        },
        "observed_comparison": observed_comparison(idle, controlled),
        "claims": {
            "virtual_wbcan_userspace_only": True,
            "physical_can": "NOT_EXECUTED",
            "mcu_or_actuator": "NOT_EXECUTED",
            "preempt_rt": "NOT_EXECUTED",
            "hard_real_time_guarantee": False,
        },
    }
    validate_campaign(campaign)
    return campaign


def validate_campaign(campaign: object) -> None:
    if not isinstance(campaign, dict):
        raise ValueError("latency campaign must be an object")
    if set(campaign) != CAMPAIGN_FIELDS:
        raise ValueError("latency campaign fields are invalid")
    if campaign.get("schema_version") != SCHEMA_VERSION or campaign.get("scope") != SCOPE:
        raise ValueError("latency campaign schema or scope is invalid")
    if campaign.get("result") != "PASS":
        raise ValueError("latency campaign result must represent complete passing evidence")
    if campaign.get("threshold_policy") != THRESHOLD_POLICY:
        raise ValueError("latency campaign must not invent a hosted-runner threshold")
    profiles = campaign.get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != {"idle", "controlled-load"}:
        raise ValueError("latency campaign profiles are incomplete")
    source_reports: dict[str, dict[str, Any]] = {}
    for profile_name in ("idle", "controlled-load"):
        entry = profiles[profile_name]
        if not isinstance(entry, dict) or not isinstance(entry.get("report"), dict):
            raise ValueError(f"latency campaign {profile_name} source is invalid")
        if set(entry) != {"source_sha256", "report"}:
            raise ValueError(f"latency campaign {profile_name} source fields are invalid")
        source_report = entry["report"]
        if entry.get("source_sha256") != _report_digest(source_report):
            raise ValueError(f"latency campaign {profile_name} source digest is invalid")
        source_reports[profile_name] = source_report
    idle = source_reports["idle"]
    controlled = source_reports["controlled-load"]
    _validate_source_reports(idle, controlled)
    expected_environment = {field: idle[field] for field in COMPARABLE_FIELDS}
    if campaign.get("environment") != expected_environment:
        raise ValueError("latency campaign environment does not match its source reports")
    if campaign.get("observed_comparison") != observed_comparison(idle, controlled):
        raise ValueError("latency campaign observed comparison is inconsistent")
    expected_claims = {
        "virtual_wbcan_userspace_only": True,
        "physical_can": "NOT_EXECUTED",
        "mcu_or_actuator": "NOT_EXECUTED",
        "preempt_rt": "NOT_EXECUTED",
        "hard_real_time_guarantee": False,
    }
    if campaign.get("claims") != expected_claims:
        raise ValueError("latency campaign contains an unsupported evidence claim")


def serialized_campaign(campaign: dict[str, Any]) -> bytes:
    validate_campaign(campaign)
    return (json.dumps(campaign, indent=2, sort_keys=True) + "\n").encode()


def write_campaign(path: Path, campaign: dict[str, Any]) -> None:
    payload = serialized_campaign(campaign)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _read_json(path: Path) -> object:
    return latency.load_json(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("idle_report", nargs="?", type=Path)
    parser.add_argument("controlled_report", nargs="?", type=Path)
    parser.add_argument("--report", type=Path, default=Path("/tmp/wbcan-latency-campaign.json"))
    parser.add_argument("--validate-report", type=Path)
    args = parser.parse_args()
    if args.validate_report is not None:
        validate_campaign(_read_json(args.validate_report))
        print(f"wbcan latency campaign valid: {args.validate_report}")
        return 0
    if args.idle_report is None or args.controlled_report is None:
        parser.error("idle_report and controlled_report are required when building a campaign")
    idle = _read_json(args.idle_report)
    controlled = _read_json(args.controlled_report)
    if not isinstance(idle, dict) or not isinstance(controlled, dict):
        parser.error("source reports must contain JSON objects")
    write_campaign(args.report, build_campaign(idle, controlled))
    print(f"wbcan latency campaign evidence: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
