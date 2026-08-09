#!/usr/bin/env python3
"""Phase-1 reachability gate: batch IK over the block and tray regions via MoveIt.

Runs the deterministic sampling from ``workbench_motion.reachability`` and, for
each sampled pose, calls MoveIt's ``/compute_ik`` service for the arm planning
group with the grasp_tcp tip. Scores each region against the >=95% threshold,
archives the numbers + seed to ``docs/evaluation/phase1-reachability.json``, and
exits non-zero if any region fails — so it can gate a build.

This is the ROS half of the gate; the sampling/scoring half is unit-tested
ROS-free in ``workbench_motion/test/test_reachability.py``. rclpy and MoveIt msgs
are imported lazily inside ``main`` so this module (and the pure module) stay
importable without ROS.

Prerequisite: a ``move_group`` for the composed arm must be running so
``/compute_ik`` is available. Bring it up first with::

    ros2 launch workbench_motion move_group.launch.py

then in another shell (installed console script)::

    ros2 run workbench_motion reachability_check --seed 0 --samples 20

Group name, tip link and planning frame default to the config/arm.yaml values.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

# The pure logic and the arm.yaml loader live in the installed package.
from workbench_motion.arm_config import load_arm_config
from workbench_motion.reachability import (
    Pose,
    Region,
    default_regions,
    sample_poses,
    score_region,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MoveIt batch reachability check")
    p.add_argument("--seed", type=int, default=0, help="RNG seed (archived for replay)")
    p.add_argument("--samples", type=int, default=20, help="poses per region (>=20 for the gate)")
    # Arm identity defaults come from config/arm.yaml, not hard-coded here. A flag
    # left unset (None) is filled from the loaded ArmConfig in main(); passing one
    # explicitly overrides config (useful for ad-hoc probing).
    p.add_argument("--arm-config", default=None, help="path to arm.yaml (default: package share / in-source)")
    p.add_argument("--group", default=None, help="planning group (default: arm.yaml planning_group)")
    p.add_argument("--tip", default=None, help="IK tip link (default: arm.yaml ik_tip_link)")
    p.add_argument("--base-frame", default=None, help="planning/pose frame (default: arm.yaml base_placement.frame)")
    p.add_argument("--threshold", type=float, default=0.95, help="per-region pass rate")
    p.add_argument("--timeout", type=float, default=2.0, help="per-IK timeout seconds")
    p.add_argument(
        "--output",
        default="docs/evaluation/phase1-reachability.json",
        help="archive path (relative to repo root)",
    )
    return p.parse_args(argv)


def _build_ik_request(
    moveit_msgs,
    geometry_msgs,
    std_msgs,
    *,
    pose: Pose,
    group: str,
    tip: str,
    frame: str,
    timeout: float,
):
    req = moveit_msgs.srv.GetPositionIK.Request()
    ik = req.ik_request
    ik.group_name = group
    ik.ik_link_name = tip
    ik.avoid_collisions = True
    ik.timeout.sec = int(timeout)
    ik.timeout.nanosec = int((timeout - int(timeout)) * 1e9)

    ps = geometry_msgs.msg.PoseStamped()
    ps.header = std_msgs.msg.Header()
    ps.header.frame_id = frame
    ps.pose.position.x = pose.x
    ps.pose.position.y = pose.y
    ps.pose.position.z = pose.z
    ps.pose.orientation.x = pose.qx
    ps.pose.orientation.y = pose.qy
    ps.pose.orientation.z = pose.qz
    ps.pose.orientation.w = pose.qw
    ik.pose_stamped = ps
    return req


def _call_ik(node, client, req, moveit_msgs, *, wait: float) -> bool:
    import rclpy

    future = client.call_async(req)
    rclpy.spin_until_future_complete(node, future, timeout_sec=wait)
    if not future.done() or future.result() is None:
        return False
    # SUCCESS == 1 in moveit_msgs/MoveItErrorCodes.
    return future.result().error_code.val == moveit_msgs.msg.MoveItErrorCodes.SUCCESS


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # arm.yaml is the single source of arm identity. CLI flags override it; unset
    # flags fall back to config. No arm-specific string is hard-coded below.
    arm = load_arm_config(args.arm_config)
    group = args.group or arm.planning_group
    tip = args.tip or arm.ik_tip_link
    base_frame = args.base_frame or arm.base_frame

    import geometry_msgs.msg
    import moveit_msgs.msg
    import moveit_msgs.srv
    import rclpy
    import std_msgs.msg
    from rclpy.node import Node

    rclpy.init()
    node = Node("reachability_check")
    client = node.create_client(moveit_msgs.srv.GetPositionIK, "/compute_ik")

    node.get_logger().info("waiting for /compute_ik (is move_group running?)")
    if not client.wait_for_service(timeout_sec=15.0):
        node.get_logger().error("/compute_ik unavailable; launch move_group first")
        node.destroy_node()
        rclpy.shutdown()
        return 2

    rng = random.Random(args.seed)
    regions: list[Region] = default_regions()
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    region_reports = []
    results = []
    for region in regions:
        poses = sample_poses(region, args.samples, rng)
        oks = []
        for pose in poses:
            req = _build_ik_request(
                moveit_msgs,
                geometry_msgs,
                std_msgs,
                pose=pose,
                group=group,
                tip=tip,
                frame=base_frame,
                timeout=args.timeout,
            )
            oks.append(_call_ik(node, client, req, moveit_msgs, wait=args.timeout + 1.0))
        res = score_region(region.name, oks, threshold=args.threshold)
        results.append(res)
        node.get_logger().info(
            f"region={res.name} success={res.successes}/{res.total} " f"rate={res.rate:.3f} pass={res.passed}"
        )
        region_reports.append(
            {
                "name": res.name,
                "total": res.total,
                "successes": res.successes,
                "rate": round(res.rate, 4),
                "threshold": res.threshold,
                "passed": res.passed,
                "bounds": {
                    "x": [region.x_min, region.x_max],
                    "y": [region.y_min, region.y_max],
                    "z": [region.z_min, region.z_max],
                },
            }
        )

    passed = bool(results) and all(r.passed for r in results)
    report = {
        "generated_at": started,
        "seed": args.seed,
        "samples_per_region": args.samples,
        "group": group,
        "tip_link": tip,
        "base_frame": base_frame,
        "threshold": args.threshold,
        "arm": arm.arm_label,
        "regions": region_reports,
        "all_passed": passed,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    node.get_logger().info(f"archived reachability report to {out} (all_passed={passed})")

    node.destroy_node()
    rclpy.shutdown()
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
