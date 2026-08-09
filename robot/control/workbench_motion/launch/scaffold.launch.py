"""Phase-0 self-test launch: bring up the scaffold node in an empty world.

Deliberately depends on nothing external (no bringup, no Gazebo, no arm). It
only proves the package installs and its node starts and logs. Later phases add
the arm + world launches.
"""

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            Node(
                package="workbench_motion",
                executable="scaffold_node",
                name="workbench_motion_scaffold",
                output="screen",
            ),
        ]
    )
