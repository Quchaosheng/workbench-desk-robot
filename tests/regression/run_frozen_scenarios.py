#!/usr/bin/env python3
"""Run the frozen scenario matrix without turning an absent simulator green.

This remains a small compatibility entry point for CI and operator scripts;
the runner implementation lives in :mod:`tools.scripts.sim_cli`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "scripts"))

from sim_cli import SimulationInputError, load_scenarios, run_scenarios


def _frozen_scenarios():
    frozen_dir = ROOT / "sim" / "scenarios" / "frozen"
    return load_scenarios(sorted(frozen_dir.glob("*.json")))


def run_scenario(manifest_path: Path, system_version: str, *, runner: str = "gazebo", command=None) -> dict:
    """Compatibility helper returning one truthful result dictionary."""

    scenarios = load_scenarios([manifest_path])
    summary = run_scenarios(
        scenarios,
        runner=runner,
        output_dir=ROOT / "runs" / "regression" / system_version,
        version=system_version,
        command=command,
    )
    return summary["results"][0]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run frozen Workbench scenarios")
    parser.add_argument("--version", required=True, help="system version label recorded in artifacts")
    parser.add_argument("--runner", choices=("gazebo", "external", "scripted"), default="gazebo")
    parser.add_argument("--runner-command", nargs="+", help="argv tokens with {manifest}, {output}, {seed}, {version}")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "runs" / "regression")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        scenarios = _frozen_scenarios()
        summary = run_scenarios(
            scenarios,
            runner=args.runner,
            output_dir=args.output_dir / args.version,
            version=args.version,
            command=args.runner_command,
        )
    except SimulationInputError as exc:
        print(f"NOT_EXECUTED: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            f"Frozen scenarios: {summary['scenario_count']} | "
            f"executed={summary['executed_count']} | "
            f"scripted={summary['scripted_count']} | "
            f"not_executed={summary['not_executed_count']} | "
            f"failed={summary['failed_count']}"
        )
        for result in summary["results"]:
            reason = f" - {result['reason']}" if result.get("reason") else ""
            print(f"  [{result['status']}] {result['scenario_id']}{reason}")

    # A regression matrix with zero real executions is never a pass. Scripted
    # fixtures are useful probes, but they are not Gazebo evidence.
    if summary["failed_count"]:
        return 1
    if summary["not_executed_count"] or summary["executed_count"] == 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
