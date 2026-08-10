"""Loader for ``config/arm.yaml`` — the single source of arm-specific identity.

The phase-1 promise (README + ADR-0004) is that swapping the arm touches
configuration only, never Python. That promise is only real if the Python that
needs the planning group, IK tip, base frame, joint list and model names *reads
them from arm.yaml* instead of hard-coding them. This module is that read path.

It resolves ``arm.yaml`` from the installed package share directory when running
under a sourced ROS workspace (``ament_index``), and falls back to the in-source
copy next to this file's package so it also works from a source checkout / uv
venv. No ROS *runtime* import (rclpy) is required; ``ament_index_python`` is a
lightweight pure-Python lookup, and even that is optional (guarded), so the
module and its callers stay importable with no ROS at all — the unit tests load a
literal path directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# In-source location: this file is workbench_motion/workbench_motion/arm_config.py;
# the config dir is workbench_motion/config/arm.yaml (two parents up, then config).
_IN_SOURCE_ARM_YAML = Path(__file__).resolve().parent.parent / "config" / "arm.yaml"


@dataclass(frozen=True)
class ArmConfig:
    """Typed view over arm.yaml. Attribute access, not dict rummaging."""

    model: str
    planning_group: str
    base_link: str
    ee_link: str
    ik_tip_link: str
    joints: tuple[str, ...]
    base_frame: str
    gripper_model: str
    gripper_group: str

    @property
    def dof(self) -> int:
        return len(self.joints)

    @property
    def arm_label(self) -> str:
        """Stable label for evidence archives, e.g. ``ur5e+robotiq_2f_85``."""
        return f"{self.model}+{self.gripper_model}"


def _find_arm_yaml() -> Path:
    """Locate arm.yaml: installed share dir first, then the in-source copy."""
    try:
        from ament_index_python.packages import (
            PackageNotFoundError,
            get_package_share_directory,
        )

        try:
            share = Path(get_package_share_directory("workbench_motion"))
            candidate = share / "config" / "arm.yaml"
            if candidate.is_file():
                return candidate
        except PackageNotFoundError:
            pass
    except ImportError:
        pass
    if _IN_SOURCE_ARM_YAML.is_file():
        return _IN_SOURCE_ARM_YAML
    raise FileNotFoundError("could not locate config/arm.yaml (installed share or in-source)")


def parse_arm_config(data: dict[str, Any]) -> ArmConfig:
    """Build an :class:`ArmConfig` from a parsed arm.yaml mapping.

    Kept separate from file IO so the unit tests can exercise the mapping->object
    contract on a literal dict without touching the filesystem or ROS.
    """
    arm = data["arm"]
    gripper = data.get("gripper", {})
    placement = data.get("base_placement", {})
    joints = tuple(arm["joints"])
    if not joints:
        raise ValueError("arm.joints must be non-empty")
    return ArmConfig(
        model=arm["model"],
        planning_group=arm["planning_group"],
        base_link=arm["base_link"],
        ee_link=arm["ee_link"],
        ik_tip_link=arm["ik_tip_link"],
        joints=joints,
        # The IK/planning frame is the workbench world root the base is fixed to.
        base_frame=placement.get("frame", "world"),
        gripper_model=gripper.get("model", "none"),
        gripper_group=gripper.get("planning_group", "gripper"),
    )


def load_arm_config(path: Path | str | None = None) -> ArmConfig:
    """Load and parse arm.yaml. ``path`` overrides discovery (used by tests)."""
    yaml_path = Path(path) if path is not None else _find_arm_yaml()
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    return parse_arm_config(data)
