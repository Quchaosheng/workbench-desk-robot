"""Unit tests for the arm.yaml loader — the single-source-of-truth contract.

The phase-1 promise is "swap the arm by editing config, not Python". These tests
assert the mechanism that makes that true: (1) the shipped config/arm.yaml parses
into a typed ArmConfig, and (2) the reachability_check CLI takes its arm identity
(group / tip / base frame) from that config, not from hard-coded strings. If
someone re-hardcodes "ur_manipulator" in the script, test (2) fails.

ROS-free: runs under `uv run pytest`. rclpy/moveit are never imported.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from workbench_motion.arm_config import ArmConfig, load_arm_config, parse_arm_config

# The shipped config, resolved from the source tree (two parents up from this test
# file's package: workbench_motion/test -> workbench_motion -> config).
_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_ARM_YAML = _CONFIG_DIR / "arm.yaml"
_SRDF = _CONFIG_DIR / "moveit" / "workbench_arm.srdf"


def test_shipped_arm_yaml_loads():
    cfg = load_arm_config(_ARM_YAML)
    assert isinstance(cfg, ArmConfig)
    assert cfg.model == "ur5e"
    assert cfg.vendor_description_pkg == "ur_description"
    assert cfg.ur_type == "ur5e"
    assert cfg.planning_group == "ur_manipulator"
    assert cfg.ik_tip_link == "grasp_tcp"
    assert cfg.base_frame == "world"
    assert cfg.dof == 6
    assert cfg.joints[0] == "shoulder_pan_joint"
    assert cfg.gripper_model == "robotiq_2f_85"
    assert cfg.driver_joint == "robotiq_85_left_knuckle_joint"
    assert cfg.update_rate_hz == 500
    assert cfg.joint_state_broadcaster == "joint_state_broadcaster"
    assert cfg.arm_trajectory_controller == "arm_trajectory_controller"
    assert cfg.gripper_controller == "gripper_controller"
    assert cfg.arm_label == "ur5e+robotiq_2f_85"


def test_shipped_arm_yaml_joint_list():
    """arm.yaml carries the 6 UR joints in chain order."""
    cfg = load_arm_config(_ARM_YAML)
    assert cfg.joints == (
        "shoulder_pan_joint",
        "shoulder_lift_joint",
        "elbow_joint",
        "wrist_1_joint",
        "wrist_2_joint",
        "wrist_3_joint",
    )


def _srdf_groups(root: ET.Element) -> dict[str, ET.Element]:
    return {g.get("name"): g for g in root.findall("group")}


def test_arm_yaml_agrees_with_srdf():
    """arm.yaml and the hand-authored SRDF must not drift apart.

    The SRDF (config/moveit/workbench_arm.srdf) is what move_group actually loads;
    arm.yaml is what the runtime Python reads. If someone edits the SRDF chain or
    renames a group without updating arm.yaml (or vice versa), IK would target a
    group/tip move_group does not expose. This parses the real SRDF (stdlib XML,
    no ROS) and asserts the arm planning group, its chain base/tip links, and the
    gripper group name match arm.yaml exactly.
    """
    cfg = load_arm_config(_ARM_YAML)
    root = ET.fromstring(_SRDF.read_text(encoding="utf-8"))
    groups = _srdf_groups(root)

    # Arm planning group exists under the name arm.yaml declares.
    assert cfg.planning_group in groups, (
        f"arm.yaml planning_group={cfg.planning_group!r} has no matching SRDF group " f"(SRDF groups: {sorted(groups)})"
    )
    # Its chain resolves IK to the tip arm.yaml names, rooted at base_link.
    chain = groups[cfg.planning_group].find("chain")
    assert chain is not None, f"SRDF group {cfg.planning_group!r} is not a chain group"
    assert chain.get("base_link") == cfg.base_link
    assert chain.get("tip_link") == cfg.ik_tip_link

    # Gripper group name matches too (arm.yaml gripper.planning_group).
    assert cfg.gripper_group in groups, (
        f"arm.yaml gripper_group={cfg.gripper_group!r} has no matching SRDF group " f"(SRDF groups: {sorted(groups)})"
    )


def test_parse_rejects_empty_joints():
    with pytest.raises(ValueError):
        parse_arm_config(
            {
                "arm": {
                    "model": "x",
                    "vendor_description_pkg": "vendor",
                    "ur_type": "x",
                    "planning_group": "g",
                    "base_link": "b",
                    "ee_link": "e",
                    "ik_tip_link": "t",
                    "joints": [],
                },
                "gripper": {"model": "g", "planning_group": "gripper", "driver_joint": "finger"},
                "controllers": {
                    "update_rate_hz": 100,
                    "joint_state_broadcaster": "jsb",
                    "arm_trajectory_controller": "arm",
                    "gripper_controller": "gripper",
                },
            }
        )


def test_parse_defaults_base_frame_to_world_when_absent():
    cfg = parse_arm_config(
        {
            "arm": {
                "model": "ur5e",
                "vendor_description_pkg": "ur_description",
                "ur_type": "ur5e",
                "planning_group": "ur_manipulator",
                "base_link": "base_link",
                "ee_link": "tool0",
                "ik_tip_link": "grasp_tcp",
                "joints": ["a"],
            },
            "gripper": {"model": "g", "planning_group": "gripper", "driver_joint": "finger"},
            "controllers": {
                "update_rate_hz": 100,
                "joint_state_broadcaster": "jsb",
                "arm_trajectory_controller": "arm",
                "gripper_controller": "gripper",
            },
        }
    )
    assert cfg.base_frame == "world"
    assert cfg.gripper_model == "g"


@pytest.mark.parametrize("missing", ["gripper", "controllers"])
def test_parse_rejects_missing_safety_sections(missing):
    data = {
        "arm": {
            "model": "ur5e",
            "vendor_description_pkg": "ur_description",
            "ur_type": "ur5e",
            "planning_group": "arm",
            "base_link": "base",
            "ee_link": "tool",
            "ik_tip_link": "tip",
            "joints": ["joint"],
        },
        "gripper": {"model": "g", "planning_group": "gripper", "driver_joint": "finger"},
        "controllers": {
            "update_rate_hz": 100,
            "joint_state_broadcaster": "jsb",
            "arm_trajectory_controller": "arm",
            "gripper_controller": "gripper",
        },
    }
    del data[missing]
    with pytest.raises(ValueError, match="missing required"):
        parse_arm_config(data)


def test_parse_rejects_missing_arm_section_as_value_error():
    with pytest.raises(ValueError, match="missing required arm configuration section: arm"):
        parse_arm_config({"gripper": {}, "controllers": {}})


def test_parse_rejects_required_identity_field_as_value_error():
    data = {
        "arm": {
            "vendor_description_pkg": "ur_description",
            "ur_type": "ur5e",
            "planning_group": "arm",
            "base_link": "base",
            "ee_link": "tool",
            "ik_tip_link": "tip",
            "joints": ["joint"],
        },
        "gripper": {"model": "g", "planning_group": "gripper", "driver_joint": "finger"},
        "controllers": {
            "update_rate_hz": 100,
            "joint_state_broadcaster": "jsb",
            "arm_trajectory_controller": "arm",
            "gripper_controller": "gripper",
        },
    }
    with pytest.raises(ValueError, match="required arm configuration field: model"):
        parse_arm_config(data)


def test_parse_rejects_missing_driver_joint():
    data = {
        "arm": {
            "model": "ur5e",
            "vendor_description_pkg": "ur_description",
            "ur_type": "ur5e",
            "planning_group": "arm",
            "base_link": "base",
            "ee_link": "tool",
            "ik_tip_link": "tip",
            "joints": ["joint"],
        },
        "gripper": {"model": "g", "planning_group": "gripper"},
        "controllers": {
            "update_rate_hz": 100,
            "joint_state_broadcaster": "jsb",
            "arm_trajectory_controller": "arm",
            "gripper_controller": "gripper",
        },
    }
    with pytest.raises(ValueError, match="driver_joint"):
        parse_arm_config(data)


@pytest.mark.parametrize("rate", [0, -1, 100.5, True])
def test_parse_rejects_invalid_controller_update_rate(rate):
    data = {
        "arm": {
            "model": "ur5e",
            "vendor_description_pkg": "ur_description",
            "ur_type": "ur5e",
            "planning_group": "arm",
            "base_link": "base",
            "ee_link": "tool",
            "ik_tip_link": "tip",
            "joints": ["joint"],
        },
        "gripper": {"model": "g", "planning_group": "gripper", "driver_joint": "finger"},
        "controllers": {
            "update_rate_hz": rate,
            "joint_state_broadcaster": "jsb",
            "arm_trajectory_controller": "arm",
            "gripper_controller": "gripper",
        },
    }
    with pytest.raises(ValueError, match="positive integer"):
        parse_arm_config(data)


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
