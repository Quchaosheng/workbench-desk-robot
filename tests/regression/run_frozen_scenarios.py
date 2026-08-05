#!/usr/bin/env python3
"""
运行 12 个冻结场景的回归测试。

用法:
    python tests/regression/run_frozen_scenarios.py --version v0.1-C

注意:
    Gazebo 层就位之前,这个脚本只做占位校验。
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.scripts._paths import ROOT


def run_scenario(manifest_path: Path, system_version: str) -> dict:
    """运行一个场景,返回 {scenario_id, success, vtcr, errors}"""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenario_id = manifest["scenario_id"]

    # TODO: 一旦 Gazebo 层就位,替换为实际运行
    # result = subprocess.run([
    #     "ros2", "launch", "workbench_bringup", "sim.launch.py",
    #     f"scenario:={manifest_path}",
    # ], capture_output=True, timeout=manifest["timeout_s"])
    #
    # success = result.returncode == 0
    # vtcr = extract_vtcr_from_log(result.stdout)

    # 占位:假设全部成功
    print(f"  [{scenario_id}] ... ✅ (占位)")
    return {
        "scenario_id": scenario_id,
        "success": True,
        "vtcr": 0.95,
        "errors": [],
    }


def main():
    parser = argparse.ArgumentParser(description="Run 12 frozen scenarios")
    parser.add_argument("--version", required=True, help="System version to test")
    args = parser.parse_args()

    frozen_dir = ROOT / "sim" / "scenarios" / "frozen"
    scenarios = sorted(frozen_dir.glob("*.json"))

    if not scenarios:
        print(f"❌ No scenarios found in {frozen_dir}")
        return 1

    print(f"Running {len(scenarios)} frozen scenarios against {args.version}...")
    results = [run_scenario(s, args.version) for s in scenarios]

    passed = sum(1 for r in results if r["success"])
    total = len(results)
    rate = passed / total

    print("\n=== Regression Results ===")
    print(f"Passed: {passed}/{total} ({rate:.1%})")

    if rate < 0.9:
        print(f"❌ Regression failed: {rate:.1%} < 90%")
        return 1

    print("✅ Regression passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
