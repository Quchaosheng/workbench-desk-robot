"""Shared parameter assembly for the phase-1 and phase-2 launch files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from launch.substitutions import Command
from launch_ros.parameter_descriptions import ParameterValue


def require_file(path: Path, what: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(
            f"{what} not found at {path}. Did you `colcon build --packages-select "
            "workbench_motion` and `source install/setup.bash`?"
        )
    return path


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def robot_description(xacro: Path, xacro_args: dict[str, str] | None = None) -> dict[str, Any]:
    require_file(xacro, "arm xacro")
    command: list[str] = ["xacro ", str(xacro)]
    for name, value in (xacro_args or {}).items():
        command.extend([f" {name}:=", value])
    return {"robot_description": ParameterValue(Command(command), value_type=str)}


def move_group_parameters(
    share: Path,
    description: dict[str, Any],
    *,
    use_sim_time: bool,
) -> list[dict[str, Any]]:
    """Assemble MoveIt parameters without creating any nodes or publishers."""
    moveit_dir = share / "config" / "moveit"
    srdf = require_file(moveit_dir / "workbench_arm.srdf", "SRDF")
    kinematics = require_file(moveit_dir / "kinematics.yaml", "kinematics.yaml")
    joint_limits = require_file(moveit_dir / "joint_limits.yaml", "joint_limits.yaml")
    ompl = require_file(moveit_dir / "ompl_planning.yaml", "ompl_planning.yaml")
    return [
        description,
        {"robot_description_semantic": ParameterValue(srdf.read_text(encoding="utf-8"), value_type=str)},
        {"robot_description_kinematics": load_yaml(kinematics)},
        {"robot_description_planning": load_yaml(joint_limits)},
        {
            "planning_pipelines": ["ompl"],
            "default_planning_pipeline": "ompl",
            "ompl": load_yaml(ompl),
        },
        {"publish_robot_description_semantic": True},
        {"use_sim_time": use_sim_time},
    ]
