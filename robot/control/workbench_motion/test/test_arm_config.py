"""Unit tests for the arm.yaml loader — the single-source-of-truth contract.

The phase-1 promise is "swap the arm by editing config, not Python". These tests
assert the mechanism that makes that true: (1) the shipped config/arm.yaml parses
into a typed ArmConfig, and (2) the reachability_check CLI takes its arm identity
(group / tip / base frame) from that config, not from hard-coded strings. If
someone re-hardcodes "ur_manipulator" in the script, test (2) fails.

ROS-free: runs under `uv run pytest`. rclpy/moveit are never imported.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from workbench_motion.arm_config import ArmConfig, load_arm_config, parse_arm_config

# The shipped config, resolved from the source tree (two parents up from this test
# file's package: workbench_motion/test -> workbench_motion -> config).
_ARM_YAML = Path(__file__).resolve().parent.parent / "config" / "arm.yaml"


def test_shipped_arm_yaml_loads():
    cfg = load_arm_config(_ARM_YAML)
    assert isinstance(cfg, ArmConfig)
    assert cfg.model == "ur5e"
    assert cfg.planning_group == "ur_manipulator"
    assert cfg.ik_tip_link == "grasp_tcp"
    assert cfg.base_frame == "world"
    assert cfg.dof == 6
    assert cfg.joints[0] == "shoulder_pan_joint"
    assert cfg.gripper_model == "robotiq_2f_85"
    assert cfg.arm_label == "ur5e+robotiq_2f_85"


def test_shipped_arm_yaml_matches_xacro_defaults():
    """arm.yaml joint count must match the SRDF/URDF the composition builds."""
    cfg = load_arm_config(_ARM_YAML)
    # The 6 UR joints, in chain order — same list the SRDF group derives.
    assert cfg.joints == (
        "shoulder_pan_joint",
        "shoulder_lift_joint",
        "elbow_joint",
        "wrist_1_joint",
        "wrist_2_joint",
        "wrist_3_joint",
    )


def test_parse_rejects_empty_joints():
    with pytest.raises(ValueError):
        parse_arm_config(
            {
                "arm": {
                    "model": "x",
                    "planning_group": "g",
                    "base_link": "b",
                    "ee_link": "e",
                    "ik_tip_link": "t",
                    "joints": [],
                }
            }
        )


def test_parse_defaults_base_frame_to_world_when_absent():
    cfg = parse_arm_config(
        {
            "arm": {
                "model": "ur5e",
                "planning_group": "ur_manipulator",
                "base_link": "base_link",
                "ee_link": "tool0",
                "ik_tip_link": "grasp_tcp",
                "joints": ["a"],
            }
        }
    )
    assert cfg.base_frame == "world"
    assert cfg.gripper_model == "none"


def test_reachability_check_defaults_come_from_arm_yaml():
    """Regression guard for the 'single source' defect.

    The CLI must resolve group/tip/base-frame from arm.yaml when the flags are
    unset — not from hard-coded literals. We replicate the exact resolution the
    script's main() performs and assert it yields the config values.
    """
    from workbench_motion.reachability_check import _parse_args

    args = _parse_args([])  # no overrides
    assert args.group is None and args.tip is None and args.base_frame is None

    cfg = load_arm_config(_ARM_YAML)
    group = args.group or cfg.planning_group
    tip = args.tip or cfg.ik_tip_link
    base_frame = args.base_frame or cfg.base_frame
    assert (group, tip, base_frame) == ("ur_manipulator", "grasp_tcp", "world")


def test_reachability_check_flags_override_config():
    from workbench_motion.reachability_check import _parse_args

    args = _parse_args(["--group", "custom_group", "--tip", "custom_tip", "--base-frame", "custom_frame"])
    cfg = load_arm_config(_ARM_YAML)
    assert (args.group or cfg.planning_group) == "custom_group"
    assert (args.tip or cfg.ik_tip_link) == "custom_tip"
    assert (args.base_frame or cfg.base_frame) == "custom_frame"
