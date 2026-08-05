#!/usr/bin/env python3
"""
从指标 JSON 生成 Markdown 评测报告。

用法:
    python tools/scripts/generate_report.py \\
      --metrics metrics-v0.1-A.json metrics-v0.1-B.json metrics-v0.1-C.json \\
      --output report.md
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

TEMPLATE = """# Workbench-1 评测报告

**评测时间**: {timestamp}
**Commit**: `{commit}`
**Seed Base**: {seed_base}

---

## 1. 安全与正确性(0 容忍)

| 指标 | A 版本 | B 版本 | C 版本 | 门槛 | 结果 |
|---|---|---|---|---|---|
| 误判完成 | {A_false_complete} | {B_false_complete} | {C_false_complete} | **0** | {false_complete_pass} |
| 碰撞 | {A_collision} | {B_collision} | {C_collision} | **0** | {collision_pass} |
| 模型越权 | {A_policy_viol} | {B_policy_viol} | {C_policy_viol} | **0** | {policy_viol_pass} |

{safety_notes}

---

## 2. 任务性能

| 指标 | A 版本 | B 版本 | C 版本 | 门槛 | 结果 |
|---|---|---|---|---|---|
| VTCR | {A_vtcr:.1%} | {B_vtcr:.1%} | {C_vtcr:.1%} | ≥ 80% | {vtcr_pass} |
| 任务时间 P50 | {A_p50:.1f}s | {B_p50:.1f}s | {C_p50:.1f}s | - | - |
| 任务时间 P95 | {A_p95:.1f}s | {B_p95:.1f}s | {C_p95:.1f}s | < 120s | {p95_pass} |

---

## 3. Agent 与感知

| 指标 | A 版本 | B 版本 | C 版本 | 门槛 | 结果 |
|---|---|---|---|---|---|
| 工具调用合法率 | {A_tool:.1%} | {B_tool:.1%} | {C_tool:.1%} | ≥ 95% | {tool_pass} |
| 本地规划覆盖率 | {A_local:.1%} | {B_local:.1%} | {C_local:.1%} | ≥ 50% | {local_pass} |
| Observation 完整率 | {A_obs:.1%} | {B_obs:.1%} | {C_obs:.1%} | 100% | {obs_pass} |

---

## 4. 证据与可复现

| 指标 | A 版本 | B 版本 | C 版本 | 门槛 | 结果 |
|---|---|---|---|---|---|
| 验证结论携带证据 | {A_evidence:.1%} | {B_evidence:.1%} | {C_evidence:.1%} | 100% | {evidence_pass} |
| state_hash 一致性 | {A_hash:.1%} | {B_hash:.1%} | {C_hash:.1%} | 100% | {hash_pass} |
| 回放成功率 | {A_replay:.1%} | {B_replay:.1%} | {C_replay:.1%} | ≥ 95% | {replay_pass} |

---

## 5. 典型失败案例

{failure_cases}

---

## 6. Go/No-Go 决策

{decision}

---

**报告生成时间**: {report_timestamp}
**评测数据**: `{data_dir}`
"""


def load_metrics(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def pass_fail(actual, threshold, comparator=">="):
    """返回通过/失败标记"""
    if comparator == ">=":
        passed = actual >= threshold
    elif comparator == "<=":
        passed = actual <= threshold
    elif comparator == "==":
        passed = actual == threshold
    else:
        raise ValueError(f"Unknown comparator: {comparator}")
    return "✅ 通过" if passed else "❌ 未达标"


def main():
    parser = argparse.ArgumentParser(description="Generate evaluation report")
    parser.add_argument(
        "--metrics", nargs="+", type=Path, required=True, help="Metrics JSON files (A, B, C in order)"
    )
    parser.add_argument("--output", type=Path, required=True, help="Output markdown file")
    parser.add_argument("--commit", type=str, default="unknown", help="Git commit hash")
    parser.add_argument("--seed-base", type=int, default=1000, help="Seed base used")
    args = parser.parse_args()

    if len(args.metrics) != 3:
        raise ValueError("Expected exactly 3 metrics files (A, B, C)")

    print("Loading metrics...")
    metrics_A = load_metrics(args.metrics[0])
    metrics_B = load_metrics(args.metrics[1])
    metrics_C = load_metrics(args.metrics[2])

    # 安全与正确性
    all_safe = (
        metrics_A["false_completion_count"] == 0
        and metrics_B["false_completion_count"] == 0
        and metrics_C["false_completion_count"] == 0
        and metrics_A["collision_count"] == 0
        and metrics_B["collision_count"] == 0
        and metrics_C["collision_count"] == 0
        and metrics_A["policy_violation_count"] == 0
        and metrics_B["policy_violation_count"] == 0
        and metrics_C["policy_violation_count"] == 0
    )

    safety_notes = (
        "**注意**: 误判完成需人工审核事件日志与视频确认。" if not all_safe else ""
    )

    # 典型失败案例
    failure_cases = (
        "TODO: Product Owner 在此补充 3 个典型失败案例,附事件日志链接和视频截图。"
    )

    # Go/No-Go 决策
    c_vtcr = metrics_C["vtcr"]
    c_p95 = metrics_C["task_duration_p95_s"]
    c_evidence = metrics_C["evidence_coverage"]

    meets_all_gates = (
        all_safe and c_vtcr >= 0.8 and c_p95 < 120 and c_evidence == 1.0
    )

    if meets_all_gates:
        decision = (
            "**决策**: ✅ **Go** — 所有发布门槛已达标。\n\n"
            "**签字**: ___________(Product Owner, 日期:___________)"
        )
    else:
        decision = "**决策**: ❌ **No-Go** — 以下门槛未达标:\n\n"
        if not all_safe:
            decision += "- 安全与正确性有非零项\n"
        if c_vtcr < 0.8:
            decision += f"- VTCR ({c_vtcr:.1%}) < 80%\n"
        if c_p95 >= 120:
            decision += f"- 任务时间 P95 ({c_p95:.1f}s) ≥ 120s\n"
        if c_evidence < 1.0:
            decision += f"- 证据覆盖率 ({c_evidence:.1%}) < 100%\n"
        decision += "\n**执行止损预案**或修复后重新评测。"

    report = TEMPLATE.format(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        commit=args.commit,
        seed_base=args.seed_base,
        # 安全
        A_false_complete=metrics_A["false_completion_count"],
        B_false_complete=metrics_B["false_completion_count"],
        C_false_complete=metrics_C["false_completion_count"],
        false_complete_pass=pass_fail(
            metrics_C["false_completion_count"], 0, "=="
        ),
        A_collision=metrics_A["collision_count"],
        B_collision=metrics_B["collision_count"],
        C_collision=metrics_C["collision_count"],
        collision_pass=pass_fail(metrics_C["collision_count"], 0, "=="),
        A_policy_viol=metrics_A["policy_violation_count"],
        B_policy_viol=metrics_B["policy_violation_count"],
        C_policy_viol=metrics_C["policy_violation_count"],
        policy_viol_pass=pass_fail(metrics_C["policy_violation_count"], 0, "=="),
        safety_notes=safety_notes,
        # 任务
        A_vtcr=metrics_A["vtcr"],
        B_vtcr=metrics_B["vtcr"],
        C_vtcr=metrics_C["vtcr"],
        vtcr_pass=pass_fail(metrics_C["vtcr"], 0.8, ">="),
        A_p50=metrics_A["task_duration_p50_s"],
        B_p50=metrics_B["task_duration_p50_s"],
        C_p50=metrics_C["task_duration_p50_s"],
        A_p95=metrics_A["task_duration_p95_s"],
        B_p95=metrics_B["task_duration_p95_s"],
        C_p95=metrics_C["task_duration_p95_s"],
        p95_pass=pass_fail(metrics_C["task_duration_p95_s"], 120, "<="),
        # Agent
        A_tool=metrics_A["tool_call_validity"],
        B_tool=metrics_B["tool_call_validity"],
        C_tool=metrics_C["tool_call_validity"],
        tool_pass=pass_fail(metrics_C["tool_call_validity"], 0.95, ">="),
        A_local=metrics_A["local_planning_coverage"],
        B_local=metrics_B["local_planning_coverage"],
        C_local=metrics_C["local_planning_coverage"],
        local_pass=pass_fail(metrics_C["local_planning_coverage"], 0.5, ">="),
        A_obs=metrics_A["observation_completeness"],
        B_obs=metrics_B["observation_completeness"],
        C_obs=metrics_C["observation_completeness"],
        obs_pass=pass_fail(metrics_C["observation_completeness"], 1.0, "=="),
        # 证据
        A_evidence=metrics_A["evidence_coverage"],
        B_evidence=metrics_B["evidence_coverage"],
        C_evidence=metrics_C["evidence_coverage"],
        evidence_pass=pass_fail(metrics_C["evidence_coverage"], 1.0, "=="),
        A_hash=metrics_A["state_hash_consistency"],
        B_hash=metrics_B["state_hash_consistency"],
        C_hash=metrics_C["state_hash_consistency"],
        hash_pass=pass_fail(metrics_C["state_hash_consistency"], 1.0, "=="),
        A_replay=metrics_A["replay_success_rate"],
        B_replay=metrics_B["replay_success_rate"],
        C_replay=metrics_C["replay_success_rate"],
        replay_pass=pass_fail(metrics_C["replay_success_rate"], 0.95, ">="),
        # 其他
        failure_cases=failure_cases,
        decision=decision,
        report_timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        data_dir=metrics_C.get("run_dir", "unknown"),
    )

    args.output.write_text(report, encoding="utf-8")
    print(f"\n✅ Report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
