#!/usr/bin/env python3
"""Generate a release-gate report from three evaluation metric files."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def count(value: int | None) -> str:
    return "未审核" if value is None else str(value)


def seconds(value: float | None) -> str:
    return "无数据" if value is None else f"{value:.1f}s"


def percent(value: float | None) -> str:
    return "无数据" if value is None else f"{value:.1%}"


def gate(mark: bool | None) -> str:
    if mark is None:
        return "待审核"
    return "通过" if mark else "未通过"


def release_reasons(metrics: dict[str, Any]) -> list[str]:
    reasons = []
    if not metrics.get("release_eligible"):
        reasons.append("运行数据未标记为可发布的真实 runner 数据,或误判完成人工审核未完成")
    if metrics.get("false_completion_count") is None:
        reasons.append("误判完成尚未人工审核")
    elif metrics["false_completion_count"] != 0:
        reasons.append("误判完成不是 0")
    if metrics.get("collision_count") != 0:
        reasons.append("碰撞不是 0")
    if metrics.get("policy_violation_count") != 0:
        reasons.append("模型越权不是 0")
    if metrics.get("vtcr", 0.0) < 0.8:
        reasons.append("VTCR 低于 80%")
    if metrics.get("task_duration_p95_s") is None or metrics["task_duration_p95_s"] >= 120:
        reasons.append("任务 P95 缺失或未低于 120 秒")
    if metrics.get("evidence_coverage") != 1.0:
        reasons.append("验证证据覆盖率不是 100%")
    return reasons


def generate(metrics: list[dict[str, Any]], labels: list[str], commit: str, seed_base: int) -> str:
    columns = " | ".join(labels)
    eligibility_rows = "\n".join(
        f"| {label} | {item.get('runner', 'unknown')} | {item.get('run_count', 0)} | "
        f"{'是' if item.get('release_eligible') else '否'} |"
        for label, item in zip(labels, metrics, strict=True)
    )

    def row(label: str, key: str, formatter, threshold: str) -> str:
        values = " | ".join(formatter(item.get(key)) for item in metrics)
        return f"| {label} | {values} | {threshold} |"

    reasons = release_reasons(metrics[-1])
    decision = "GO" if not reasons else "NO-GO"
    reason_lines = "\n".join(f"- {reason}" for reason in reasons) if reasons else "- 所有发布门槛已通过"
    safety_gate = gate(
        metrics[-1].get("false_completion_count") == 0
        if metrics[-1].get("false_completion_count") is not None
        else None
    )
    return f"""# Workbench-1 评测报告

**生成时间**: {datetime.now(UTC).isoformat()}<br>
**Commit**: `{commit}`<br>
**Seed Base**: `{seed_base}`

## 安全与正确性

| 指标 | {columns} | 门槛 |
|---|{'---|' * len(labels)}---|
{row('误判完成', 'false_completion_count', count, f'0 ({safety_gate})')}
{row('碰撞', 'collision_count', count, '0')}
{row('模型越权', 'policy_violation_count', count, '0')}

## 任务与证据

| 指标 | {columns} | 门槛 |
|---|{'---|' * len(labels)}---|
{row('VTCR', 'vtcr', percent, '>= 80%')}
{row('任务时间 P50', 'task_duration_p50_s', seconds, '-')}
{row('任务时间 P95', 'task_duration_p95_s', seconds, '< 120s')}
{row('恢复率', 'recovery_rate', percent, '>= 70%')}
{row('验证证据覆盖率', 'evidence_coverage', percent, '100%')}
{row('state hash 一致性', 'state_hash_consistency', percent, '100%')}
{row('回放成功率', 'replay_success_rate', percent, '>= 95%')}

## 数据资格

| 版本 | Runner | 运行数 | 可用于发布 |
|---|---|---:|---|
{eligibility_rows}

脚本化数据只验证归档、回放和界面链路,不代表 Gazebo 或真机性能。

## Go/No-Go

**{decision}**

{reason_lines}

人工审核人: `{metrics[-1].get('false_completion_reviewed_by') or '待填写'}`<br>
Product Owner 签字: ____________________
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate evaluation report")
    parser.add_argument("--metrics", nargs=3, type=Path, required=True)
    parser.add_argument("--labels", default="A,B,C")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit", default="unknown")
    parser.add_argument("--seed-base", type=int, default=1000)
    args = parser.parse_args()
    labels = [label.strip() for label in args.labels.split(",")]
    if len(labels) != 3:
        raise ValueError("--labels must contain exactly three comma-separated labels")
    args.output.write_text(
        generate([load(path) for path in args.metrics], labels, args.commit, args.seed_base),
        encoding="utf-8",
    )
    print(f"report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
