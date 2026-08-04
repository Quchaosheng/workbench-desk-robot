#!/usr/bin/env python3
"""
批量运行 36 次评测(12 场景 × 3 版本)。

用法:
    python tools/scripts/run_evaluation.py \\
      --versions v0.1-A,v0.1-B,v0.1-C \\
      --scenarios sim/scenarios/frozen/*.json \\
      --output-dir evaluation/run-20260804-1000/results

注意:
    Gazebo 层就位之前,这个脚本只创建占位日志。
    Integration Owner 在 Gazebo 就位后填充实际运行逻辑。
"""
import argparse
import json
import subprocess
from pathlib import Path


def run_one_scenario(version: str, scenario: Path, output_dir: Path, seed_base: int) -> bool:
    """运行一个场景,保存事件日志(JSON Lines 格式)"""
    scenario_id = scenario.stem
    output_file = output_dir / f"{scenario_id}.json"

    print(f"  {version} / {scenario_id} ... ", end="", flush=True)

    # TODO: 一旦 Gazebo 层就位,替换为实际运行命令
    # 实际命令示例:
    # result = subprocess.run(
    #     [
    #         "ros2", "launch", "workbench_bringup", "sim.launch.py",
    #         f"scenario:={scenario}",
    #         f"output:={output_file}",
    #         f"seed_base:={seed_base}",
    #     ],
    #     capture_output=True,
    #     text=True,
    #     timeout=600,
    # )
    # success = result.returncode == 0

    # 占位:生成假的事件日志
    manifest = json.loads(scenario.read_text(encoding="utf-8"))
    fake_events = [
        {
            "event_id": "evt-001",
            "run_id": f"{scenario_id}-{version}",
            "sequence_no": 1,
            "event_type": "observation",
            "occurred_at": "2026-08-04T10:00:00Z",
            "payload": {
                "entity_id": "red_block",
                "confidence": 0.98,
                "observation_id": "obs-001",
                "run_id": f"{scenario_id}-{version}",
                "entity_type": "block",
                "pose": {
                    "frame_id": "world",
                    "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
                },
            },
            "evidence_refs": ["camera-frame-001"],
        },
        {
            "event_id": "evt-002",
            "run_id": f"{scenario_id}-{version}",
            "sequence_no": 2,
            "event_type": "verification",
            "occurred_at": "2026-08-04T10:01:00Z",
            "payload": {
                "completed": True,
                "reason": "object location matches tray relation",
                "evidence_refs": ["verification-001"],
            },
            "evidence_refs": ["verification-001"],
        },
    ]

    output_file.write_text(
        "\n".join(json.dumps(e) for e in fake_events) + "\n", encoding="utf-8"
    )
    print("✅ (占位数据)")
    return True


def main():
    parser = argparse.ArgumentParser(description="Run 36 evaluation runs")
    parser.add_argument(
        "--versions", required=True, help="Comma-separated version tags (e.g., v0.1-A,v0.1-B,v0.1-C)"
    )
    parser.add_argument("--scenarios", nargs="+", type=Path, required=True, help="Scenario manifest files")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output directory")
    parser.add_argument("--seed-base", type=int, default=1000, help="Seed base for reproducibility")
    args = parser.parse_args()

    versions = args.versions.split(",")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Running {len(versions)} versions × {len(args.scenarios)} scenarios = {len(versions) * len(args.scenarios)} runs")
    print(f"Seed base: {args.seed_base}")
    print()

    results = {}
    for version in versions:
        version_dir = args.output_dir / version
        version_dir.mkdir(exist_ok=True)
        print(f"[{version}]")

        success_count = 0
        for scenario in sorted(args.scenarios):
            if run_one_scenario(version, scenario, version_dir, args.seed_base):
                success_count += 1

        results[version] = {
            "total": len(args.scenarios),
            "success": success_count,
            "rate": success_count / len(args.scenarios),
        }
        print()

    print("\n=== Summary ===")
    for version, stats in results.items():
        print(f"{version}: {stats['success']}/{stats['total']} ({stats['rate']:.1%})")

    if all(s["rate"] >= 0.9 for s in results.values()):
        print("\n✅ All versions passed (≥ 90%)")
        return 0
    else:
        print("\n❌ Some versions failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
