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
    candidate_yaws,
    default_regions,
    is_gate_qualifying,
    poses_at,
    sample_positions,
    score_region,
    validate_run_params,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MoveIt batch reachability check")
    p.add_argument("--seed", type=int, default=0, help="RNG seed (archived for replay)")
    p.add_argument("--samples", type=int, default=20, help="positions per region (>=20 for the gate)")
    p.add_argument("--yaws", type=int, default=12, help="candidate approach yaws per position (symmetric [0,pi))")
    # Arm identity defaults come from config/arm.yaml, not hard-coded here. A flag
    # left unset (None) is filled from the loaded ArmConfig in main(); passing one
    # explicitly overrides config (useful for ad-hoc probing).
    p.add_argument("--arm-config", default=None, help="path to arm.yaml (default: package share / in-source)")
    p.add_argument("--group", default=None, help="planning group (default: arm.yaml planning_group)")
    p.add_argument("--tip", default=None, help="IK tip link (default: arm.yaml ik_tip_link)")
    p.add_argument("--base-frame", default=None, help="planning/pose frame (default: arm.yaml base_placement.frame)")
    p.add_argument("--threshold", type=float, default=0.95, help="per-region pass rate (gate needs >=0.95)")
    p.add_argument(
        "--probe",
        action="store_true",
        help="allow sub-gate params (samples<20 or threshold<0.95) for ad-hoc probing; "
        "the report is stamped gate_qualifying=false and the process exits non-zero",
    )
    # Default matches config/moveit/kinematics.yaml kinematics_solver_timeout
    # (0.05 s): the TRAC-IK solver already stops at 0.05, so a larger per-request
    # timeout would not give the solver more budget. Kept as one knob for a
    # coherent, reproducible number recorded into the report as ik_timeout_s.
    p.add_argument("--timeout", type=float, default=0.05, help="per-IK timeout seconds (matches solver timeout)")
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
    sensor_msgs,
    *,
    pose: Pose,
    group: str,
    tip: str,
    frame: str,
    joints: tuple[str, ...],
    timeout: float,
    collide: bool = True,
):
    req = moveit_msgs.srv.GetPositionIK.Request()
    ik = req.ik_request
    ik.group_name = group
    ik.ik_link_name = tip
    # collide=True -> collision-aware (the real gate). collide=False -> pure
    # kinematic reach, archived alongside as a diagnostic.
    ik.avoid_collisions = collide
    ik.timeout.sec = int(timeout)
    ik.timeout.nanosec = int((timeout - int(timeout)) * 1e9)

    # Seed the full robot_state the GetPositionIK contract expects. Without a
    # populated JointState, move_group logs "Found empty JointState message" for
    # every request and falls back to the current state; supplying the arm joints
    # at a neutral 0.0 seed satisfies the contract and makes the seed explicit and
    # reproducible. Joint names come from arm.yaml (single source), not hard-coded.
    js = sensor_msgs.msg.JointState()
    js.name = list(joints)
    js.position = [0.0] * len(joints)
    ik.robot_state.joint_state = js

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

    # Hard bounds: reject meaningless params before doing any work.
    validate_run_params(samples=args.samples, yaws=args.yaws, threshold=args.threshold)
    # Soft gate: sub-gate params are only allowed under --probe, and never count
    # as a gate pass. This stops `--samples 1 --threshold 0` from producing a
    # green acceptance report.
    gate_qualifying = is_gate_qualifying(samples=args.samples, threshold=args.threshold)
    if not gate_qualifying and not args.probe:
        print(
            f"refusing sub-gate run (samples={args.samples}, threshold={args.threshold}): "
            f"the phase-1 gate needs samples>=20 and threshold>=0.95. "
            f"Re-run with --probe to explicitly do a non-qualifying probe.",
            file=sys.stderr,
        )
        return 2

    import geometry_msgs.msg
    import moveit_msgs.msg
    import moveit_msgs.srv
    import rclpy
    import sensor_msgs.msg
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
    yaws = candidate_yaws(args.yaws)
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    def _ik(pose: Pose, *, collide: bool) -> bool:
        req = _build_ik_request(
            moveit_msgs,
            geometry_msgs,
            std_msgs,
            sensor_msgs,
            pose=pose,
            group=group,
            tip=tip,
            frame=base_frame,
            joints=arm.joints,
            timeout=args.timeout,
            collide=collide,
        )
        return _call_ik(node, client, req, moveit_msgs, wait=args.timeout + 1.0)

    region_reports = []
    results = []
    for region in regions:
        positions = sample_positions(region, args.samples, rng)
        # Per-position graspability (the gate): >=1 collision-free IK-valid yaw.
        graspable: list[bool] = []
        # Diagnostics kept visible: pure kinematic reach + collision-free yaw margin.
        pure_reach: list[bool] = []
        yaw_margins: list[int] = []
        for pos in positions:
            poses = poses_at(pos, yaws)
            free = sum(1 for p in poses if _ik(p, collide=True))
            yaw_margins.append(free)
            graspable.append(free > 0)
            # pure reach: does any yaw solve ignoring collisions (kinematics only)
            pure_reach.append(any(_ik(p, collide=False) for p in poses))
        res = score_region(region.name, graspable, threshold=args.threshold)
        results.append(res)
        pure_rate = sum(pure_reach) / len(pure_reach) if pure_reach else 0.0
        node.get_logger().info(
            f"region={res.name} graspable={res.successes}/{res.total} "
            f"rate={res.rate:.3f} pass={res.passed} pure_reach={pure_rate:.3f} "
            f"yaw_margin(min/median)={min(yaw_margins)}/{sorted(yaw_margins)[len(yaw_margins) // 2]}"
        )
        region_reports.append(
            {
                "name": res.name,
                "positions": res.total,
                "graspable": res.successes,
                "rate": round(res.rate, 4),
                "threshold": res.threshold,
                "passed": res.passed,
                "pure_reach_rate": round(pure_rate, 4),
                "yaw_margin_min": min(yaw_margins),
                "yaw_margin_max": max(yaw_margins),
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
        "yaws_per_position": args.yaws,
        "ik_timeout_s": args.timeout,
        "metric": "position graspable if >=1 top-down yaw is collision-free and IK-valid",
        "group": group,
        "tip_link": tip,
        "base_frame": base_frame,
        "threshold": args.threshold,
        "arm": arm.arm_label,
        # gate_qualifying=false marks a probe run whose params are too weak to be
        # a phase-1 acceptance signal, even if all regions "passed".
        "gate_qualifying": gate_qualifying,
        "regions": region_reports,
        "all_passed": passed,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    node.get_logger().info(
        f"archived reachability report to {out} (all_passed={passed}, gate_qualifying={gate_qualifying})"
    )

    node.destroy_node()
    rclpy.shutdown()
    # A run only "succeeds" (rc 0) if regions passed AND the params qualify as a
    # gate. A non-qualifying probe exits non-zero so CI can never treat it as green.
    return 0 if (passed and gate_qualifying) else 1


if __name__ == "__main__":
    sys.exit(main())
