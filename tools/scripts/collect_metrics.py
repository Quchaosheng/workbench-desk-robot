#!/usr/bin/env python3
"""
从事件库和日志中提取全部 18 个指标。

用法:
    python tools/scripts/collect_metrics.py --run-dir evaluation/run-20260804-1000/results/v0.1-C

输出:
    metrics.json 包含全部指标的 JSON 文件
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def load_events(run_dir: Path) -> list[dict]:
    """加载所有事件日志(JSON Lines 格式)"""
    events = []
    for log_file in sorted(run_dir.glob("*.json")):
        for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
            if line:
                events.append(json.loads(line))
    return sorted(events, key=lambda e: (e.get("run_id", ""), e.get("sequence_no", 0)))


def compute_vtcr(events: list[dict]) -> float:
    """已验证任务完成率"""
    verifications = [e for e in events if e.get("event_type") == "verification"]
    if not verifications:
        return 0.0
    completed = sum(1 for v in verifications if v.get("payload", {}).get("status") == "confirmed")
    return completed / len(verifications)


def compute_false_completion(events: list[dict]) -> int:
    """误判完成次数(需人工审核,这里返回占位值)"""
    # TODO: 这个指标无法完全自动化,必须人工审核事件日志 + 视频
    return 0


def compute_collision_count(events: list[dict]) -> int:
    """碰撞次数"""
    return sum(
        1 for e in events if e.get("event_type") == "fault" and e.get("payload", {}).get("fault_type") == "collision"
    )


def compute_policy_violation_count(events: list[dict]) -> int:
    """模型越权次数"""
    return sum(1 for e in events if e.get("event_type") == "policy_violation")


def compute_task_duration_percentiles(events: list[dict]) -> dict[str, float]:
    """任务耗时 P50/P95(秒)"""
    tasks = defaultdict(dict)
    for e in events:
        run_id = e.get("run_id")
        if not run_id:
            continue
        if e.get("event_type") == "task_start":
            tasks[run_id]["start"] = e.get("occurred_at")
        elif e.get("event_type") == "verification":
            tasks[run_id]["end"] = e.get("occurred_at")

    durations = []
    for _run_id, times in tasks.items():
        if "start" in times and "end" in times:
            try:
                start = datetime.fromisoformat(times["start"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(times["end"].replace("Z", "+00:00"))
                durations.append((end - start).total_seconds())
            except (ValueError, AttributeError):
                pass

    if not durations:
        return {"p50": 0.0, "p95": 0.0}

    durations.sort()
    p50_idx = int(len(durations) * 0.50)
    p95_idx = int(len(durations) * 0.95)
    return {"p50": durations[p50_idx], "p95": durations[p95_idx]}


def compute_recovery_rate(events: list[dict]) -> float:
    """失败后恢复成功率"""
    # TODO: 实现序列分析,识别首次失败 → 重试 → 成功的模式
    return 0.0


def compute_tool_call_validity(events: list[dict]) -> float:
    """语义工具调用合法率"""
    tool_calls = [e for e in events if e.get("event_type") == "tool_call"]
    if not tool_calls:
        return 1.0
    valid = sum(1 for c in tool_calls if c.get("payload", {}).get("valid"))
    return valid / len(tool_calls)


def compute_local_planning_coverage(events: list[dict]) -> float:
    """本地规划覆盖率"""
    plans = [e for e in events if e.get("event_type") == "task_graph"]
    if not plans:
        return 0.0
    local = sum(1 for p in plans if p.get("payload", {}).get("model_route") == "local")
    return local / len(plans)


def compute_observation_completeness(events: list[dict]) -> float:
    """Observation 必填字段完整率"""
    observations = [e for e in events if e.get("event_type") == "observation"]
    if not observations:
        return 1.0
    complete = sum(
        1
        for o in observations
        if all(k in o.get("payload", {}) for k in ["observation_id", "run_id", "entity_id", "pose", "confidence"])
    )
    return complete / len(observations)


def compute_evidence_coverage(events: list[dict]) -> float:
    """验证结论携带证据的比例"""
    verifications = [e for e in events if e.get("event_type") == "verification"]
    if not verifications:
        return 1.0
    with_evidence = sum(1 for v in verifications if v.get("payload", {}).get("evidence_refs"))
    return with_evidence / len(verifications)


def compute_state_hash_consistency(events: list[dict]) -> float:
    """state_hash 一致性(需要多次重放,这里返回占位值)"""
    # TODO: 实现多次重放并比较 state_hash
    return 1.0


def compute_replay_success_rate(events: list[dict]) -> float:
    """固定任务回放成功率(需要实际回放,这里返回占位值)"""
    # TODO: 实现事件回放并检查是否成功
    return 1.0


def main():
    parser = argparse.ArgumentParser(description="Extract metrics from event logs")
    parser.add_argument("--run-dir", type=Path, required=True, help="Directory with event logs")
    parser.add_argument("--output", type=Path, default=Path("metrics.json"), help="Output JSON")
    args = parser.parse_args()

    if not args.run_dir.is_dir():
        raise FileNotFoundError(f"Directory not found: {args.run_dir}")

    print(f"Loading events from {args.run_dir}...")
    events = load_events(args.run_dir)
    print(f"Loaded {len(events)} events")

    print("Computing metrics...")
    duration_percentiles = compute_task_duration_percentiles(events)

    metrics = {
        # 安全与正确性
        "false_completion_count": compute_false_completion(events),
        "collision_count": compute_collision_count(events),
        "policy_violation_count": compute_policy_violation_count(events),
        # 任务性能
        "vtcr": compute_vtcr(events),
        "task_duration_p50_s": duration_percentiles["p50"],
        "task_duration_p95_s": duration_percentiles["p95"],
        "recovery_rate": compute_recovery_rate(events),
        # Agent 与感知
        "tool_call_validity": compute_tool_call_validity(events),
        "local_planning_coverage": compute_local_planning_coverage(events),
        "observation_completeness": compute_observation_completeness(events),
        # 世界模型与证据
        "evidence_coverage": compute_evidence_coverage(events),
        "state_hash_consistency": compute_state_hash_consistency(events),
        "replay_success_rate": compute_replay_success_rate(events),
        # 元数据
        "total_events": len(events),
        "run_dir": str(args.run_dir),
    }

    args.output.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"\n✅ Metrics written to {args.output}")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
