"""Attack-style tests for the ROS-free phase-2 joint-limit validator."""

from __future__ import annotations

import copy
import math
from typing import ClassVar

import pytest
from workbench_motion.joint_limits import (
    JointLimit,
    check_trajectory,
    effective_limits,
    load_hard_limits,
    load_hw_override,
)

JOINTS = ("j1", "j2")
LIMITS = {
    "j1": JointLimit(-2.0, 2.0, 1.0, 10.0),
    "j2": JointLimit(-3.0, 3.0, 2.0, 20.0),
}
CURRENT = {"j1": 0.0, "j2": 0.0}


def trajectory(*points, names=JOINTS):
    return {"joint_names": list(names), "points": list(points)}


def point(t, positions=(0.0, 0.0), velocities=(), accelerations=(), effort=()):
    return {
        "positions": list(positions),
        "velocities": list(velocities),
        "accelerations": list(accelerations),
        "effort": list(effort),
        "time_from_start": t,
    }


def check(traj, current=CURRENT, *, epsilon=1e-6):
    return check_trajectory(traj, current, LIMITS, limit_epsilon=epsilon)


def test_loads_real_vendor_degrees_and_all_six_joints():
    limits = load_hard_limits("ur_description", "ur5e")
    assert len(limits) == 6
    assert math.isclose(limits["shoulder_pan_joint"].max_position, 2 * math.pi)
    assert math.isclose(limits["shoulder_pan_joint"].max_velocity, math.pi)
    assert limits["wrist_1_joint"].max_effort == 28.0


def test_hw_override_empty_and_missing_joint_are_allowed(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    assert load_hw_override(empty, hard_limits=LIMITS) == {}
    partial = tmp_path / "partial.yaml"
    partial.write_text("joint_limits:\n  j1:\n    max_velocity: 0.5\n", encoding="utf-8")
    loaded = load_hw_override(partial, hard_limits=LIMITS)
    assert loaded["j1"].max_velocity == 0.5
    assert "j2" not in loaded


def test_shipped_default_hw_override_is_empty_and_loadable():
    hard = load_hard_limits("ur_description", "ur5e")
    assert load_hw_override(hard_limits=hard) == {}


@pytest.mark.parametrize(
    "yaml_text,match",
    [
        ("joint_limits:\n  typo:\n    max_velocity: 0.5\n", "unknown joint"),
        ("joint_limits:\n  j1:\n    max_velocity: 1.1\n", "looser"),
        ("joint_limits:\n  j1:\n    min_position: -2.1\n", "looser"),
        ("joint_limits:\n  j1:\n    max_position: 2.1\n", "looser"),
        ("joint_limits:\n  j1:\n    max_effort: 11\n", "looser"),
        ("joint_limits:\n  j1:\n    min_position: 1\n    max_position: 0\n", "min_position"),
        ("joint_limits:\n  j1:\n    max_velocity: fast\n", "finite number"),
        ("joint_limits:\n  j1:\n    degrees: 90\n", "unknown fields"),
    ],
)
def test_hw_override_fails_closed(yaml_text, match, tmp_path):
    path = tmp_path / "override.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        load_hw_override(path, hard_limits=LIMITS)


def test_effective_limits_intersects_without_planning_scaling():
    override = {"j1": JointLimit(-1.0, 1.5, 0.4, 8.0)}
    result = effective_limits(LIMITS, override)
    assert result["j1"] == override["j1"]
    assert result["j2"] == LIMITS["j2"]


def test_legal_trajectory_passes_and_input_is_not_mutated():
    traj = trajectory(point(0.0), point(1.0, (0.5, 1.0), velocities=(0.5, 1.0), effort=(1.0, 2.0)))
    before = copy.deepcopy(traj)
    assert check(traj) is None
    assert traj == before


@pytest.mark.parametrize(
    "traj,current,kind",
    [
        ({"points": [point(0.0)]}, CURRENT, "joint_names"),
        (trajectory(point(0.0), names=()), CURRENT, "joint_names"),
        (trajectory(point(0.0), names=("j1", "j1")), CURRENT, "joint_names"),
        (trajectory(point(0.0), names=("j1", "unknown")), CURRENT, "joint_names"),
        (trajectory({"positions": [0.0], "time_from_start": 0.0}, names=("j1",)), CURRENT, "joint_names"),
        (trajectory(), CURRENT, "points"),
        (trajectory(point(0.0, positions=(0.0,))), CURRENT, "array_length"),
        (trajectory(point(0.0, velocities=(0.0,))), CURRENT, "array_length"),
        (trajectory(point(0.0, accelerations=(0.0,))), CURRENT, "array_length"),
        (trajectory(point(0.0, effort=(0.0,))), CURRENT, "array_length"),
        (trajectory(point(0.0)), {"j1": 0.0}, "current_state"),
        (trajectory(point(0.0)), {"j1": 0.0, "j2": 0.0, "x": 0.0}, "current_state"),
        (trajectory(point(0.0)), {"j1": math.nan, "j2": 0.0}, "non_finite"),
        (trajectory(point(0.0)), {"j1": 2.0, "j2": 0.0}, "current_position"),
        (trajectory(point(-0.1)), CURRENT, "time"),
        (trajectory(point(0.0), point(0.0)), CURRENT, "time"),
        (trajectory(point(0.0, positions=(math.nan, 0.0))), CURRENT, "non_finite"),
    ],
)
def test_malformed_or_unsafe_trajectory_fails_closed(traj, current, kind):
    assert check(traj, current).kind == kind


@pytest.mark.parametrize(
    "candidate,kind,joint",
    [
        (trajectory(point(1.0, positions=(2.0, 0.0))), "position", "j1"),
        (trajectory(point(1.0, velocities=(1.0, 0.0))), "velocity", "j1"),
        (trajectory(point(1.0, effort=(10.0, 0.0))), "effort", "j1"),
        (trajectory(point(0.0, positions=(0.01, 0.0))), "initial_position", "j1"),
        (trajectory(point(0.1, positions=(0.2, 0.0))), "segment_velocity", "j1"),
        (trajectory(point(0.0), point(0.1, positions=(0.2, 0.0))), "segment_velocity", "j1"),
    ],
)
def test_limit_attacks_are_rejected(candidate, kind, joint):
    violation = check(candidate)
    assert violation is not None
    assert (violation.kind, violation.joint) == (kind, joint)


def test_t0_zero_accepts_current_within_epsilon():
    assert check(trajectory(point(0.0, positions=(5e-7, 0.0)))) is None


def test_epsilon_tightens_instead_of_widening_hard_bound():
    violation = check(trajectory(point(3.0, positions=(1.9999995, 0.0))), epsilon=1e-6)
    assert violation is not None and violation.kind == "position"


@pytest.mark.parametrize("epsilon", [-1.0, math.inf, math.nan])
def test_invalid_epsilon_is_rejected(epsilon):
    with pytest.raises(ValueError, match="limit_epsilon"):
        check(trajectory(point(0.0)), epsilon=epsilon)


class Duration:
    sec = 1
    nanosec = 500_000_000


class Point:
    positions: ClassVar[list[float]] = [0.5, 1.0]
    velocities: ClassVar[list[float]] = []
    accelerations: ClassVar[list[float]] = []
    effort: ClassVar[list[float]] = []
    time_from_start = Duration()


class RosLikeTrajectory:
    joint_names: ClassVar[list[str]] = list(JOINTS)
    points: ClassVar[list[Point]] = [Point()]


def test_accepts_ros_message_shaped_objects_without_importing_ros():
    assert check(RosLikeTrajectory()) is None
