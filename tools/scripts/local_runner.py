#!/usr/bin/env python3
"""Run a bounded template or localhost-only model planner."""

import argparse
import json
import os
import sys
from pathlib import Path

from _paths import enable_local_packages

enable_local_packages()

from workbench_agent_runtime import OllamaModelProvider, build_local_model_plan, build_template_plan


def plan_offline(
    goal: str,
    *,
    provider_name: str = "template",
    model: str = "qwen2.5:0.5b",
    endpoint: str = "http://127.0.0.1:11434",
    timeout_s: float = 120.0,
    allowed_hosts: set[str] | None = None,
) -> dict:
    if provider_name == "template":
        plan = build_template_plan(goal)
        model_call = None
        network_access = "disabled"
    elif provider_name == "ollama":
        provider = OllamaModelProvider(
            model,
            endpoint=endpoint,
            timeout_s=timeout_s,
            allowed_hosts=allowed_hosts,
        )
        plan = build_local_model_plan(goal, provider)
        model_call = provider.last_call
        network_access = "local_only"
    else:
        raise ValueError(f"unsupported provider: {provider_name}")
    return {
        "offline": True,
        "provider": plan.planner if provider_name == "template" else provider_name,
        "network_access": network_access,
        "model_call": model_call,
        "task_graph": plan.model_dump(mode="json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded local Workbench-1 planner")
    parser.add_argument("--goal", help="Task goal; stdin is used when omitted")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--provider", choices=("template", "ollama"), default="template")
    parser.add_argument("--model", default=os.environ.get("WORKBENCH_MODEL", "qwen2.5:0.5b"))
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("WORKBENCH_MODEL_ENDPOINT", "http://127.0.0.1:11434"),
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        help="Explicitly allow a local container-network hostname such as model",
    )
    args = parser.parse_args()
    goal = args.goal or sys.stdin.read().strip()
    if not goal:
        raise ValueError("a non-empty goal is required")
    os.environ["WORKBENCH_OFFLINE"] = "1"
    payload = plan_offline(
        goal,
        provider_name=args.provider,
        model=args.model,
        endpoint=args.endpoint,
        timeout_s=args.timeout,
        allowed_hosts=set(args.allow_host),
    )
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
