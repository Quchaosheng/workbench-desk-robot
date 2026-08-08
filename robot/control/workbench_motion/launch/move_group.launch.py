"""Bring up move_group for the composed UR5e + Robotiq arm (phase 1).

Purpose: provide ``/compute_ik`` (and a planning scene from the merged URDF) so
``scripts/reachability_check.py`` can run the batch IK reachability gate, and so
the arm can be inspected in RViz. This is Motion's own minimal launch — it does
NOT depend on any external bringup (PLAN.md §阶段 1).

Path resolution note: ``robot/description`` is not a ROS package (no package.xml;
different owner), so it cannot be found via ``$(find ...)``. This launch resolves
the arm and workbench xacros from the launch file's own location in the source
tree and exposes both as overridable launch arguments. Run it from the source
tree (or a ``colcon build --symlink-install`` workspace) so ``__file__`` points
at the real files:

    ros2 launch workbench_motion move_group.launch.py

Override paths for a relocated layout:

    ros2 launch workbench_motion move_group.launch.py \
        arm_xacro:=/abs/arm_on_workbench.urdf.xacro \
        workbench_xacro:=/abs/workbench.urdf.xacro

Requires: ros-jazzy-moveit, ros-jazzy-trac-ik-kinematics-plugin (kinematics.yaml).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

# launch dir = robot/control/workbench_motion/launch
_LAUNCH_DIR = Path(__file__).resolve().parent
_PKG_DIR = _LAUNCH_DIR.parent  # robot/control/workbench_motion
_REPO_ROOT = _PKG_DIR.parent.parent.parent  # repo root
_CONFIG_DIR = _PKG_DIR / "config"
_MOVEIT_DIR = _CONFIG_DIR / "moveit"

_DEFAULT_ARM_XACRO = str(_CONFIG_DIR / "arm_on_workbench.urdf.xacro")
_DEFAULT_WORKBENCH_XACRO = str(_REPO_ROOT / "robot" / "description" / "workbench.urdf.xacro")


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _setup(context, *_args, **_kwargs) -> list[Node]:
    arm_xacro = LaunchConfiguration("arm_xacro").perform(context)
    workbench_xacro = LaunchConfiguration("workbench_xacro").perform(context)

    # Expand the composed URDF, threading the workbench path through the xacro arg.
    robot_description = {
        "robot_description": ParameterValue(
            Command(["xacro ", arm_xacro, " workbench_xacro:=", workbench_xacro]),
            value_type=str,
        )
    }
    robot_description_semantic = {
        "robot_description_semantic": ParameterValue(
            (_MOVEIT_DIR / "workbench_arm.srdf").read_text(encoding="utf-8"),
            value_type=str,
        )
    }
    kinematics = {"robot_description_kinematics": _load_yaml(_MOVEIT_DIR / "kinematics.yaml")}
    joint_limits = {"robot_description_planning": _load_yaml(_MOVEIT_DIR / "joint_limits.yaml")}
    ompl = _load_yaml(_MOVEIT_DIR / "ompl_planning.yaml")

    move_group = Node(
        package="moveit_ros_move_group",
        executable="move_group",
        output="screen",
        parameters=[
            robot_description,
            robot_description_semantic,
            kinematics,
            joint_limits,
            ompl,
            {"publish_robot_description_semantic": True},
            {"use_sim_time": False},
        ],
    )
    rsp = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="screen",
        parameters=[robot_description, {"use_sim_time": False}],
    )
    # Static joint states so TF is complete for IK/collision (no controllers yet;
    # ros2_control lands in phase 2). GUI off for headless CI runs.
    jsp = Node(
        package="joint_state_publisher",
        executable="joint_state_publisher",
        output="screen",
        parameters=[{"use_sim_time": False}],
    )
    return [rsp, jsp, move_group]


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument("arm_xacro", default_value=_DEFAULT_ARM_XACRO),
            DeclareLaunchArgument("workbench_xacro", default_value=_DEFAULT_WORKBENCH_XACRO),
            OpaqueFunction(function=_setup),
        ]
    )
