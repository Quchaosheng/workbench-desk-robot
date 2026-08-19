"""Bring up move_group for the composed UR5e + Robotiq arm (phase 1).

Purpose: provide ``/compute_ik`` (and a planning scene from the merged URDF) so
the ``reachability_check`` console script can run the batch IK reachability gate,
and so the arm can be inspected in RViz. This is Motion's own minimal launch — it
does NOT depend on any external bringup (PLAN.md §阶段 1).

Path resolution: everything is resolved from the *installed* package share via
``ament_index`` (``get_package_share_directory``), so it works after a normal
``colcon build`` (not only ``--symlink-install``). setup.py installs the config
tree and a vendored copy of the workbench world xacro into the share dir, and the
composed xacro finds the world via ``$(find workbench_motion)`` — no reliance on
the source-tree layout at runtime. Requires the workspace to be sourced::

    colcon build --packages-select workbench_motion
    source install/setup.bash
    ros2 launch workbench_motion move_group.launch.py

The arm xacro path is exposed as an overridable, validated launch argument.

Requires: ros-jazzy-moveit, ros-jazzy-trac-ik-kinematics-plugin (kinematics.yaml).
"""

from __future__ import annotations

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from workbench_motion.launch_utils import move_group_parameters, require_file, robot_description

_SHARE = Path(get_package_share_directory("workbench_motion"))
_CONFIG_DIR = _SHARE / "config"
_DEFAULT_ARM_XACRO = str(_CONFIG_DIR / "arm_on_workbench.urdf.xacro")


def _setup(context, *_args, **_kwargs) -> list[Node]:
    arm_xacro = Path(LaunchConfiguration("arm_xacro").perform(context))
    require_file(arm_xacro, "arm xacro")
    description = robot_description(arm_xacro)
    moveit_params = move_group_parameters(_SHARE, description, use_sim_time=False)

    move_group = Node(
        package="moveit_ros_move_group",
        executable="move_group",
        output="screen",
        parameters=moveit_params,
    )
    rsp = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="screen",
        parameters=[description, {"use_sim_time": False}],
    )
    # Static joint states so TF is complete for IK/collision (no controllers yet;
    # ros2_control lands in phase 2).
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
            OpaqueFunction(function=_setup),
        ]
    )
