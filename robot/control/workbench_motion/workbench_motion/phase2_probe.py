#!/usr/bin/env python3
"""Phase-2 controller/TF/collision/mimic evidence probe.

ROS imports are lazy. Classification, path densification, mimic math, report
validation, and orchestration stay ROS-free and are unit-tested with fake IO.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Protocol

from workbench_motion.arm_config import ArmConfig, load_arm_config
from workbench_motion.joint_limits import (
    JointLimit,
    Violation,
    check_trajectory,
    effective_limits,
    load_hard_limits,
    load_hw_override,
)

SAFE_BEHAVIORS = frozenset({"rejected", "aborted"})
FAIL_BEHAVIORS = frozenset({"clamped", "executed_over_limit", "timeout", "unclassified"})
FOLLOWERS = {
    "robotiq_85_right_knuckle_joint": -1.0,
    "robotiq_85_left_inner_knuckle_joint": 1.0,
    "robotiq_85_right_inner_knuckle_joint": -1.0,
    "robotiq_85_left_finger_tip_joint": -1.0,
    "robotiq_85_right_finger_tip_joint": 1.0,
}
TF_CHAIN = (
    "world",
    "base_link",
    "base_link_inertia",
    "shoulder_link",
    "upper_arm_link",
    "forearm_link",
    "wrist_1_link",
    "wrist_2_link",
    "wrist_3_link",
    "flange",
    "tool0",
    "grasp_tcp",
)


@dataclass(frozen=True)
class JointSnapshot:
    positions: dict[str, float]
    stamp_s: float


@dataclass(frozen=True)
class ActionObservation:
    accepted: bool
    status: str
    timed_out: bool
    requested: dict[str, float]
    before: JointSnapshot
    after: JointSnapshot
    samples: tuple[JointSnapshot, ...] = ()


class ProbeIO(Protocol):
    def endpoint_status(self) -> Mapping[str, bool]: ...
    def robot_description(self) -> str: ...
    def controller_states(self) -> list[dict[str, str]]: ...
    def tf_chain(self, frames: Sequence[str], staleness_s: float) -> dict[str, Any]: ...
    def joint_snapshot(self, staleness_s: float) -> JointSnapshot: ...
    def execute_arm(self, target: Mapping[str, float], duration_s: float, staleness_s: float) -> ActionObservation: ...
    def collision_check(self, states: Sequence[Mapping[str, float]]) -> dict[str, Any]: ...
    def execute_gripper(self, position: float, staleness_s: float) -> ActionObservation: ...
    def versions(self) -> Mapping[str, str]: ...


def _resolve_output_path(output: str, start: Path | None = None) -> Path:
    path = Path(output)
    if path.is_absolute():
        return path
    start = start or Path.cwd()
    for parent in (start, *start.parents):
        if (parent / ".git").exists():
            return parent / path
    return path


def is_stale(stamp_s: float, now_s: float, staleness_s: float) -> bool:
    if not all(math.isfinite(value) for value in (stamp_s, now_s, staleness_s)) or staleness_s < 0:
        return True
    return stamp_s <= 0.0 or now_s - stamp_s > staleness_s or stamp_s > now_s + staleness_s


def hardware_is_gazebo(robot_description: str) -> bool:
    return "<plugin>gz_ros2_control/GazeboSimSystem</plugin>" in robot_description


def snapshot_is_complete(snapshot: JointSnapshot, required_joints: Sequence[str]) -> bool:
    """Return true only for a finite snapshot containing every controlled joint."""
    if not math.isfinite(snapshot.stamp_s) or snapshot.stamp_s <= 0.0:
        return False
    return all(joint in snapshot.positions and math.isfinite(snapshot.positions[joint]) for joint in required_joints)


def _outside(
    snapshot: JointSnapshot, limits: Mapping[str, JointLimit], epsilon: float = 1e-6
) -> list[dict[str, float | str]]:
    found = []
    for joint, limit in limits.items():
        value = snapshot.positions.get(joint)
        if value is None or not math.isfinite(value):
            continue
        if value < limit.min_position - epsilon:
            found.append({"joint": joint, "value": value, "bound": limit.min_position})
        elif value > limit.max_position + epsilon:
            found.append({"joint": joint, "value": value, "bound": limit.max_position})
    return found


def classify_over_limit(
    observation: ActionObservation, limits: Mapping[str, JointLimit], tolerance: float = 0.01
) -> str:
    """Classify actual controller behavior into the frozen six-class taxonomy."""
    required = tuple(limits)
    snapshots = (observation.before, *observation.samples, observation.after)
    # An incomplete /joint_states message is evidence failure, never evidence
    # that an aborted goal was safe.  This is deliberately checked before the
    # action status so an empty after snapshot cannot produce "aborted".
    if any(not snapshot_is_complete(sample, required) for sample in snapshots):
        return "unclassified"
    if observation.timed_out:
        return "timeout"
    samples = (*observation.samples, observation.after)
    if any(_outside(sample, limits) for sample in samples):
        return "executed_over_limit"
    moved = any(
        abs(observation.after.positions.get(joint, before) - before) > tolerance
        for joint, before in observation.before.positions.items()
    )
    if not observation.accepted:
        return "rejected" if not moved else "unclassified"
    clamped = False
    for joint, requested in observation.requested.items():
        limit = limits.get(joint)
        actual = observation.after.positions.get(joint)
        if limit is None or actual is None or not math.isfinite(actual):
            continue
        if requested < limit.min_position and abs(actual - limit.min_position) <= tolerance:
            clamped = True
        elif requested > limit.max_position and abs(actual - limit.max_position) <= tolerance:
            clamped = True
    if moved and clamped:
        return "clamped"
    if observation.status == "aborted":
        return "aborted" if not moved else "unclassified"
    return "unclassified"


def smoothness_report(
    samples: Sequence[JointSnapshot],
    target: Mapping[str, float],
    *,
    velocity_jump_limit: float = 1.0,
    overshoot_tolerance: float = 0.01,
) -> dict[str, Any]:
    """Machine-check sampled trajectory timing, velocity jumps and overshoot."""
    joints = tuple(target)
    report: dict[str, Any] = {
        "samples_checked": len(samples),
        "velocity_jump_limit_rad_s": velocity_jump_limit,
        "overshoot_tolerance_rad": overshoot_tolerance,
        "velocity_continuous": False,
        "overshoot_free": False,
        "max_velocity_jump_rad_s": None,
        "valid": False,
        "reason": None,
    }
    if len(samples) < 2 or any(not snapshot_is_complete(sample, joints) for sample in samples):
        report["reason"] = "insufficient_or_invalid_joint_state_samples"
        return report
    velocities: list[dict[str, float]] = []
    for previous, current in pairwise(samples):
        dt = current.stamp_s - previous.stamp_s
        if not math.isfinite(dt) or dt <= 0.0:
            report["reason"] = "non_increasing_sample_timestamps"
            return report
        velocities.append({joint: (current.positions[joint] - previous.positions[joint]) / dt for joint in joints})
    jumps = [abs(current[joint] - previous[joint]) for previous, current in pairwise(velocities) for joint in joints]
    max_jump = max(jumps, default=0.0)
    report["max_velocity_jump_rad_s"] = max_jump
    report["velocity_continuous"] = max_jump <= velocity_jump_limit
    overshoot = False
    for joint in joints:
        start = samples[0].positions[joint]
        goal = target[joint]
        direction = goal - start
        if abs(direction) <= overshoot_tolerance:
            continue
        for sample in samples[1:]:
            progress = sample.positions[joint] - start
            if (direction > 0 and progress > direction + overshoot_tolerance) or (
                direction < 0 and progress < direction - overshoot_tolerance
            ):
                overshoot = True
                break
    report["overshoot_free"] = not overshoot
    report["valid"] = report["velocity_continuous"] and report["overshoot_free"]
    if not report["valid"]:
        report["reason"] = "velocity_jump_or_overshoot"
    return report


def behavior_gate(kind: str) -> str:
    if kind in SAFE_BEHAVIORS:
        return "safe"
    if kind in FAIL_BEHAVIORS:
        return "fail"
    raise ValueError(f"unknown over-limit behavior {kind!r}")


def mimic_ratios(
    before: Mapping[str, float],
    after: Mapping[str, float],
    driver_joint: str,
    followers: Mapping[str, float] = FOLLOWERS,
    tolerance_abs: float = 0.02,
) -> dict[str, Any]:
    driver_delta = after[driver_joint] - before[driver_joint]
    if not math.isfinite(driver_delta) or abs(driver_delta) <= 1e-9:
        raise ValueError("gripper driver did not move; mimic ratios are undefined")
    entries = []
    for joint, nominal in followers.items():
        observed = (after[joint] - before[joint]) / driver_delta
        entries.append(
            {
                "joint": joint,
                "nominal_multiplier": nominal,
                "observed_ratio": observed,
                "ok": math.isfinite(observed) and abs(observed - nominal) <= tolerance_abs,
            }
        )
    return {
        "control_declaration": "explicit_followers_with_vendor_multipliers",
        "tolerance_abs": tolerance_abs,
        "driver_joint": driver_joint,
        "followers": entries,
        "all_ok": all(entry["ok"] for entry in entries),
    }


def densify_joint_path(states: Sequence[Mapping[str, float]], resolution_rad: float = 0.05) -> list[dict[str, float]]:
    if not math.isfinite(resolution_rad) or resolution_rad <= 0:
        raise ValueError("resolution_rad must be positive and finite")
    if not states:
        return []
    result = [dict(states[0])]
    joints = set(states[0])
    for start, end in pairwise(states):
        if set(start) != joints or set(end) != joints:
            raise ValueError("all path states must contain the same joints")
        steps = max(1, math.ceil(max(abs(end[j] - start[j]) for j in joints) / resolution_rad))
        for step in range(1, steps + 1):
            alpha = step / steps
            result.append({joint: start[joint] + alpha * (end[joint] - start[joint]) for joint in joints})
    return result


def validate_report(report: Mapping[str, Any]) -> None:
    required = {
        "generated_at",
        "commit",
        "git_dirty",
        "config_hashes",
        "versions",
        "arm",
        "controllers",
        "tf_chain",
        "gripper_mimic",
        "legal_trajectory",
        "observed_controller_over_limit_behavior",
        "validator_violation",
        "all_passed",
    }
    missing = required - set(report)
    if missing:
        raise ValueError(f"phase-2 report is missing fields: {sorted(missing)}")
    kind = report["observed_controller_over_limit_behavior"].get("kind")
    if kind not in SAFE_BEHAVIORS | FAIL_BEHAVIORS:
        raise ValueError(f"invalid over-limit classification: {kind!r}")
    legal = report["legal_trajectory"]
    smoothness = legal.get("smoothness") if isinstance(legal, Mapping) else None
    if not isinstance(smoothness, Mapping) or not isinstance(smoothness.get("valid"), bool):
        raise ValueError("legal_trajectory.smoothness is missing or invalid")


def atomic_write_report(path: Path, report: Mapping[str, Any]) -> None:
    validate_report(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _git_metadata(repo: Path) -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True).stdout
    )
    return commit, dirty


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _command_version(command: list[str]) -> str:
    if shutil.which(command[0]) is None:
        return "unavailable"
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=5.0)
    output = (completed.stdout or completed.stderr).strip()
    return output.splitlines()[0] if output else "unknown"


def _deb_version(package: str) -> str:
    return _command_version(["dpkg-query", "-W", "-f=${Version}", package])


def _snapshot_dict(snapshot: JointSnapshot) -> dict[str, Any]:
    return {"stamp_s": snapshot.stamp_s, "positions": snapshot.positions}


def _violation_dict(violation: Violation | None) -> dict[str, Any] | None:
    return asdict(violation) if violation is not None else None


def run_probe(
    io: ProbeIO,
    *,
    arm: ArmConfig,
    limits: Mapping[str, JointLimit],
    output: Path,
    repo: Path,
    config_dir: Path,
    staleness_s: float = 1.0,
    collision_check_resolution_rad: float = 0.05,
) -> int:
    """Run the probe and publish evidence only after every gate has data."""

    def fail(code: int, reason: str) -> int:
        print(f"phase2_probe: {reason}", file=sys.stderr)
        return code

    try:
        endpoints = dict(io.endpoint_status())
        if not endpoints or not all(endpoints.values()):
            unavailable = sorted(name for name, available in endpoints.items() if not available)
            return fail(2, f"required endpoints unavailable: {unavailable}")
        description = io.robot_description()
        if not hardware_is_gazebo(description):
            return fail(2, "robot_description is not using gz_ros2_control/GazeboSimSystem")
        controllers = io.controller_states()
        expected = {arm.joint_state_broadcaster, arm.arm_trajectory_controller, arm.gripper_controller}
        if {entry["name"] for entry in controllers if entry.get("state") == "active"} != expected:
            return fail(2, "the expected controller set is not active")
        tf_report = io.tf_chain(TF_CHAIN, staleness_s)
        if not tf_report.get("present"):
            return fail(2, f"TF chain is incomplete or stale: {tf_report}")
        before = io.joint_snapshot(staleness_s)
        if not snapshot_is_complete(before, arm.joints):
            return fail(2, "initial /joint_states is incomplete or non-finite")
        current = {joint: before.positions[joint] for joint in arm.joints}
        legal_target = dict(current)
        joint = arm.joints[0]
        direction = -1.0 if current[joint] + 0.05 >= limits[joint].max_position else 1.0
        legal_target[joint] += direction * 0.05
        legal = io.execute_arm(legal_target, 2.0, staleness_s)
        path = densify_joint_path([current, legal_target], collision_check_resolution_rad)
        path.extend(sample.positions for sample in legal.samples)
        collision = io.collision_check(path)
        collision["resolution_rad"] = collision_check_resolution_rad
        legal_samples = [legal.before, *legal.samples, legal.after]
        # A fake or controller may report the terminal sample both in its
        # history and as ``after``; retain one copy so equal timestamps do not
        # masquerade as a discontinuity.
        legal_samples = [
            sample
            for index, sample in enumerate(legal_samples)
            if index == 0 or sample.stamp_s != legal_samples[index - 1].stamp_s
        ]
        smoothness = smoothness_report(legal_samples, legal_target)
        tracking_ok = snapshot_is_complete(legal.after, arm.joints) and all(
            abs(legal.after.positions[j] - legal_target[j]) <= 0.05 for j in arm.joints
        )
        if legal.status != "succeeded" or not tracking_ok or not smoothness["valid"] or not collision.get("all_valid"):
            return fail(
                2,
                f"legal trajectory gate failed: status={legal.status}, "
                f"tracking_ok={tracking_ok}, smoothness={smoothness}, collision={collision}",
            )

        over_target = dict(legal_target)
        over_target[joint] = limits[joint].max_position + 0.1
        validator_traj = {
            "joint_names": list(arm.joints),
            "points": [{"positions": [over_target[j] for j in arm.joints], "time_from_start": 2.0}],
        }
        validator = check_trajectory(validator_traj, {j: legal.after.positions[j] for j in arm.joints}, limits)
        if validator is None:
            return fail(2, "local validator accepted the over-limit trajectory")
        over = io.execute_arm(over_target, 2.0, staleness_s)
        kind = classify_over_limit(over, limits)
        gate = behavior_gate(kind)

        gripper_before = io.joint_snapshot(staleness_s)
        gripper = io.execute_gripper(0.5, staleness_s)
        if gripper.status != "succeeded" or gripper.timed_out:
            return fail(2, f"gripper action failed: status={gripper.status}, timed_out={gripper.timed_out}")
        mimic = mimic_ratios(gripper_before.positions, gripper.after.positions, arm.driver_joint)
        if not mimic["all_ok"]:
            return fail(2, f"gripper mimic ratio gate failed: {mimic}")

        commit, dirty = _git_metadata(repo)
        report = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "commit": commit,
            "git_dirty": dirty,
            "config_hashes": {
                "arm.yaml": _sha256(config_dir / "arm.yaml"),
                "controllers.yaml": _sha256(config_dir / "controllers.yaml"),
            },
            "versions": dict(io.versions()),
            "arm": arm.arm_label,
            "controllers": controllers,
            "tf_chain": tf_report,
            "gripper_mimic": mimic,
            "legal_trajectory": {
                "tracking_tolerance_rad": 0.05,
                "joint_states_before": _snapshot_dict(legal.before),
                "joint_states_after": _snapshot_dict(legal.after),
                "tracking_ok": tracking_ok,
                "smoothness": smoothness,
                "collision": collision,
            },
            "observed_controller_over_limit_behavior": {
                "kind": kind,
                "gate": gate,
                "is_phase4_bypass_risk": kind in {"clamped", "executed_over_limit"},
                "joint_states_before": _snapshot_dict(over.before),
                "joint_states_after": _snapshot_dict(over.after),
                "over_limit_joints": _outside(over.after, limits),
            },
            "validator_violation": _violation_dict(validator),
            "all_passed": gate == "safe" and mimic["all_ok"] and collision["all_valid"] and tf_report["present"],
        }
        if not report["all_passed"]:
            return fail(1, f"observed controller over-limit behavior is {kind!r}")
        atomic_write_report(output, report)
        return 0
    except (KeyError, ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        return fail(2, f"{type(exc).__name__}: {exc}")


class RosProbeIO:
    """Small synchronous adapter over the ROS services/actions used by the probe."""

    def __init__(self, arm: ArmConfig, timeout_s: float = 10.0):
        import rclpy
        from control_msgs.action import FollowJointTrajectory, GripperCommand
        from controller_manager_msgs.srv import ListControllers
        from moveit_msgs.srv import GetStateValidity
        from rclpy.action import ActionClient
        from rclpy.node import Node
        from rclpy.parameter import Parameter
        from rclpy.parameter_client import AsyncParameterClient
        from sensor_msgs.msg import JointState
        from tf2_ros import Buffer, TransformListener

        self.rclpy = rclpy
        self.arm = arm
        self.timeout_s = timeout_s
        self.node = Node(
            "phase2_probe",
            parameter_overrides=[Parameter("use_sim_time", Parameter.Type.BOOL, True)],
        )
        self.list_client = self.node.create_client(ListControllers, "/controller_manager/list_controllers")
        self.state_client = self.node.create_client(GetStateValidity, "/check_state_validity")
        self.arm_action = ActionClient(
            self.node, FollowJointTrajectory, f"/{arm.arm_trajectory_controller}/follow_joint_trajectory"
        )
        self.gripper_action = ActionClient(self.node, GripperCommand, f"/{arm.gripper_controller}/gripper_cmd")
        self.parameter_client = AsyncParameterClient(self.node, "/robot_state_publisher")
        self.tf_buffer = Buffer(node=self.node)
        self.tf_listener = TransformListener(self.tf_buffer, self.node)
        self.latest: JointSnapshot | None = None
        self.history: list[JointSnapshot] = []
        self.node.create_subscription(JointState, "/joint_states", self._on_joint_state, 50)

    def _spin(self, future, timeout_s: float | None = None):
        self.rclpy.spin_until_future_complete(self.node, future, timeout_sec=timeout_s or self.timeout_s)
        return future.result() if future.done() else None

    def _on_joint_state(self, message):
        if len(message.name) != len(message.position) or len(set(message.name)) != len(message.name):
            return
        stamp = float(message.header.stamp.sec) + float(message.header.stamp.nanosec) / 1e9
        snapshot = JointSnapshot(dict(zip(message.name, message.position, strict=False)), stamp)
        # Keep malformed messages visible as a missing fresh sample.  The
        # consumer then times out/fails closed instead of treating them as a
        # safe action result.
        if snapshot_is_complete(snapshot, self.arm.joints):
            self.latest = snapshot
            self.history.append(snapshot)

    def endpoint_status(self) -> Mapping[str, bool]:
        return {
            "list_controllers": self.list_client.wait_for_service(timeout_sec=self.timeout_s),
            "check_state_validity": self.state_client.wait_for_service(timeout_sec=self.timeout_s),
            "arm_action": self.arm_action.wait_for_server(timeout_sec=self.timeout_s),
            "gripper_action": self.gripper_action.wait_for_server(timeout_sec=self.timeout_s),
            "robot_description": self.parameter_client.wait_for_services(timeout_sec=self.timeout_s),
        }

    def robot_description(self) -> str:
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            result = self._spin(
                self.parameter_client.get_parameters(["robot_description"]),
                min(2.0, remaining),
            )
            if result is not None and result.values and result.values[0].string_value:
                return result.values[0].string_value
        raise RuntimeError("robot_description unavailable")

    def controller_states(self) -> list[dict[str, str]]:
        from controller_manager_msgs.srv import ListControllers

        result = self._spin(self.list_client.call_async(ListControllers.Request()))
        if result is None:
            raise RuntimeError("ListControllers timed out")
        return [{"name": item.name, "type": item.type, "state": item.state} for item in result.controller]

    def tf_chain(self, frames: Sequence[str], staleness_s: float) -> dict[str, Any]:
        from rclpy.time import Time
        from tf2_ros import TransformException

        pending = {(parent, child): "missing" for parent, child in pairwise(frames)}
        deadline = time.monotonic() + self.timeout_s
        while pending and time.monotonic() < deadline:
            self.rclpy.spin_once(self.node, timeout_sec=0.1)
            now = self.node.get_clock().now().nanoseconds / 1e9
            for parent, child in tuple(pending):
                try:
                    transform = self.tf_buffer.lookup_transform(parent, child, Time())
                    stamp = transform.header.stamp.sec + transform.header.stamp.nanosec / 1e9
                    if stamp > 0.0 and is_stale(stamp, now, staleness_s):
                        pending[(parent, child)] = "stale"
                    else:
                        del pending[(parent, child)]
                except TransformException:
                    continue
        missing = [f"{parent}->{child}" for (parent, child), state in pending.items() if state == "missing"]
        stale = [f"{parent}->{child}" for (parent, child), state in pending.items() if state == "stale"]
        return {"expected": list(frames), "present": not missing and not stale, "missing": missing, "stale": stale}

    def joint_snapshot(self, staleness_s: float) -> JointSnapshot:
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            self.rclpy.spin_once(self.node, timeout_sec=0.1)
            now = self.node.get_clock().now().nanoseconds / 1e9
            if (
                self.latest is not None
                and snapshot_is_complete(self.latest, self.arm.joints)
                and not is_stale(self.latest.stamp_s, now, staleness_s)
            ):
                return self.latest
        raise RuntimeError("fresh /joint_states unavailable")

    def execute_arm(self, target: Mapping[str, float], duration_s: float, staleness_s: float) -> ActionObservation:
        from action_msgs.msg import GoalStatus
        from control_msgs.action import FollowJointTrajectory
        from trajectory_msgs.msg import JointTrajectoryPoint

        before = self.joint_snapshot(staleness_s)
        history_start = len(self.history)
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = list(self.arm.joints)
        point = JointTrajectoryPoint()
        point.positions = [target[joint] for joint in self.arm.joints]
        point.time_from_start.sec = int(duration_s)
        point.time_from_start.nanosec = int((duration_s - int(duration_s)) * 1e9)
        goal.trajectory.points = [point]
        goal_handle = self._spin(self.arm_action.send_goal_async(goal))
        if goal_handle is None:
            return ActionObservation(False, "unknown", True, dict(target), before, before)
        if not goal_handle.accepted:
            after = self.joint_snapshot(staleness_s)
            return ActionObservation(
                False, "rejected", False, dict(target), before, after, tuple(self.history[history_start:])
            )
        wrapped = self._spin(goal_handle.get_result_async(), duration_s + self.timeout_s)
        if wrapped is None:
            after = self.joint_snapshot(staleness_s)
            return ActionObservation(
                True, "unknown", True, dict(target), before, after, tuple(self.history[history_start:])
            )
        status = {
            GoalStatus.STATUS_SUCCEEDED: "succeeded",
            GoalStatus.STATUS_ABORTED: "aborted",
            GoalStatus.STATUS_CANCELED: "canceled",
        }.get(wrapped.status, "unknown")
        after = self.joint_snapshot(staleness_s)
        return ActionObservation(True, status, False, dict(target), before, after, tuple(self.history[history_start:]))

    def collision_check(self, states: Sequence[Mapping[str, float]]) -> dict[str, Any]:
        from moveit_msgs.srv import GetStateValidity
        from sensor_msgs.msg import JointState

        first_invalid = None
        for index, state in enumerate(states):
            request = GetStateValidity.Request()
            request.group_name = self.arm.planning_group
            request.robot_state.joint_state = JointState(
                name=list(self.arm.joints), position=[state[j] for j in self.arm.joints]
            )
            response = self._spin(self.state_client.call_async(request))
            if response is None:
                raise RuntimeError("/check_state_validity timed out")
            if not response.valid and first_invalid is None:
                first_invalid = {"index": index, "positions": dict(state)}
        return {
            "source": "moveit",
            "resolution_rad": 0.05,
            "states_checked": len(states),
            "all_valid": first_invalid is None,
            "first_invalid": first_invalid,
        }

    def execute_gripper(self, position: float, staleness_s: float) -> ActionObservation:
        from action_msgs.msg import GoalStatus
        from control_msgs.action import GripperCommand

        before = self.joint_snapshot(staleness_s)
        start = len(self.history)
        goal = GripperCommand.Goal()
        goal.command.position = position
        goal.command.max_effort = 20.0
        handle = self._spin(self.gripper_action.send_goal_async(goal))
        if handle is None or not handle.accepted:
            return ActionObservation(
                False, "rejected", handle is None, {self.arm.driver_joint: position}, before, before
            )
        wrapped = self._spin(handle.get_result_async(), self.timeout_s)
        after = self.joint_snapshot(staleness_s)
        status = "succeeded" if wrapped is not None and wrapped.status == GoalStatus.STATUS_SUCCEEDED else "aborted"
        return ActionObservation(
            True, status, wrapped is None, {self.arm.driver_joint: position}, before, after, tuple(self.history[start:])
        )

    def versions(self) -> Mapping[str, str]:
        return {
            "ros_distro": os.environ.get("ROS_DISTRO", "unknown"),
            "gz": _command_version(["gz", "sim", "--versions"]),
            "gz_ros2_control": _deb_version("ros-jazzy-gz-ros2-control"),
            "jtc": _deb_version("ros-jazzy-joint-trajectory-controller"),
            "gripper_controllers": _deb_version("ros-jazzy-gripper-controllers"),
        }

    def close(self):
        self.node.destroy_node()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase-2 Gazebo controller evidence probe")
    parser.add_argument("--arm-config", default=None)
    parser.add_argument("--output", default="docs/evaluation/phase2-controllers.json")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--staleness", type=float, default=1.0)
    parser.add_argument("--collision-resolution", type=float, default=0.05)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    arm = load_arm_config(args.arm_config)
    hard = load_hard_limits(arm.vendor_description_pkg, arm.ur_type)
    limits = effective_limits(hard, load_hw_override(hard_limits=hard))
    output = _resolve_output_path(args.output)
    repo = next((parent for parent in (Path.cwd(), *Path.cwd().parents) if (parent / ".git").exists()), Path.cwd())
    if args.arm_config:
        config_dir = Path(args.arm_config).parent
    else:
        from ament_index_python.packages import get_package_share_directory

        config_dir = Path(get_package_share_directory("workbench_motion")) / "config"

    import rclpy

    rclpy.init()
    io = RosProbeIO(arm, args.timeout)
    try:
        return run_probe(
            io,
            arm=arm,
            limits=limits,
            output=output,
            repo=repo,
            config_dir=config_dir,
            staleness_s=args.staleness,
            collision_check_resolution_rad=args.collision_resolution,
        )
    finally:
        io.close()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
