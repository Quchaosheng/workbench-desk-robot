"""Structural consistency checks for phase-2 control configuration."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml
from workbench_motion.arm_config import load_arm_config

CONFIG = Path(__file__).resolve().parent.parent / "config"
LAUNCH = Path(__file__).resolve().parent.parent / "launch"


def test_controller_names_joints_and_rate_match_arm_yaml():
    arm = load_arm_config(CONFIG / "arm.yaml")
    controllers = yaml.safe_load((CONFIG / "controllers.yaml").read_text(encoding="utf-8"))
    manager = controllers["controller_manager"]["ros__parameters"]
    assert manager["update_rate"] == arm.update_rate_hz
    assert manager[arm.joint_state_broadcaster]["type"] == "joint_state_broadcaster/JointStateBroadcaster"
    assert manager[arm.arm_trajectory_controller]["type"] == "joint_trajectory_controller/JointTrajectoryController"
    assert manager[arm.gripper_controller]["type"] == "position_controllers/GripperActionController"
    assert tuple(controllers[arm.arm_trajectory_controller]["ros__parameters"]["joints"]) == arm.joints
    assert controllers[arm.gripper_controller]["ros__parameters"]["joint"] == arm.driver_joint
    constraints = controllers[arm.arm_trajectory_controller]["ros__parameters"]["constraints"]
    assert constraints["goal_time"] > 0
    for joint in arm.joints:
        assert 0 < constraints[joint]["goal"] <= 0.05


def test_xacro_control_is_opt_in_and_reuses_vendor_macro():
    composed = (CONFIG / "arm_on_workbench.urdf.xacro").read_text(encoding="utf-8")
    control = (CONFIG / "ros2_control.xacro").read_text(encoding="utf-8")
    assert re.search(r'<xacro:arg name="sim_gz"\s+default="false"', composed)
    assert "ur_joint_control_description" in control
    assert "gz_ros2_control/GazeboSimSystem" in control
    assert "<plugin>ign_ros2_control/" not in control
    assert "joint_limits" not in control


def test_gripper_control_declares_vendor_mimic_followers_as_state_only():
    control = (CONFIG / "ros2_control.xacro").read_text(encoding="utf-8")
    followers = {
        "robotiq_85_right_knuckle_joint": "-1",
        "robotiq_85_left_inner_knuckle_joint": "1",
        "robotiq_85_right_inner_knuckle_joint": "-1",
        "robotiq_85_left_finger_tip_joint": "-1",
        "robotiq_85_right_finger_tip_joint": "1",
    }
    for joint, multiplier in followers.items():
        block = re.search(rf'<joint name="\$\{{tf_prefix\}}{joint}">(.*?)</joint>', control, re.DOTALL)
        assert block is not None
        assert '<param name="mimic">${tf_prefix}${driver_joint}</param>' in block.group(1)
        assert f'<param name="multiplier">{multiplier}</param>' in block.group(1)
        assert '<state_interface name="position"/>' in block.group(1)
        assert '<state_interface name="velocity"/>' in block.group(1)
        assert "command_interface" not in block.group(1)


def test_xacro_defaults_match_arm_config():
    arm = load_arm_config(CONFIG / "arm.yaml")
    root = ET.fromstring((CONFIG / "arm_on_workbench.urdf.xacro").read_text(encoding="utf-8"))
    ns = {"xacro": "http://www.ros.org/wiki/xacro"}
    defaults = {arg.attrib["name"]: arg.attrib["default"] for arg in root.findall("xacro:arg", ns)}
    assert defaults["ur_type"] == arm.ur_type
    assert defaults["driver_joint"] == arm.driver_joint


def test_sim_launch_is_headless_and_does_not_start_joint_state_publisher():
    launch = (LAUNCH / "sim_control.launch.py").read_text(encoding="utf-8")
    assert '"gz_args": "-s -r -v 3 empty.sdf"' in launch
    assert 'package="robot_state_publisher"' in launch
    assert 'package="joint_state_publisher"' not in launch
    assert "use_sim_time=True" in launch


def test_sim_launch_bridges_clock_only():
    launch = (LAUNCH / "sim_control.launch.py").read_text(encoding="utf-8")
    assert 'package="ros_gz_bridge"' in launch
    assert '"/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock"' in launch
    assert "/contacts" not in launch


def test_sim_launch_shutdown_reason_names_each_failed_controller():
    launch = (LAUNCH / "sim_control.launch.py").read_text(encoding="utf-8")
    assert "failed_process: str" in launch
    assert "_next_if_success(arm.joint_state_broadcaster, arm_controller)" in launch
    assert "_next_if_success(arm.arm_trajectory_controller, gripper)" in launch
    assert "_next_if_success(arm.gripper_controller)" in launch
