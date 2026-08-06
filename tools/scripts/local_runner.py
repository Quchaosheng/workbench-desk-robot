#!/usr/bin/env python3
"""Run the frozen template planner with no network or model service."""

import argparse
import json
import os
import sys
from pathlib import Path

from _paths import enable_local_packages

enable_local_packages()

from workbench_agent_runtime import build_template_plan


def plan_offline(goal: str) -> dict:
    plan = build_template_plan(goal)
    return {
        "offline": True,
        "provider": "template-v1",
        "network_access": "disabled",
        "task_graph": plan.model_dump(mode="json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local deterministic Workbench-1 planner")
    parser.add_argument("--goal", help="Task goal; stdin is used when omitted")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    goal = args.goal or sys.stdin.read().strip()
    if not goal:
        raise ValueError("a non-empty goal is required")
    os.environ["WORKBENCH_OFFLINE"] = "1"
    payload = plan_offline(goal)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
