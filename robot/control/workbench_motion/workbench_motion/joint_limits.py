"""ROS-free hard-limit loading and conservative trajectory validation.

The validator deliberately checks only vendor hard limits intersected with the
optional hardware override. MoveIt's planning limits and scaling remain in the
planning layer. This module judges; it never clamps, dispatches, or emits events.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from workbench_motion.arm_config import load_arm_config

DEFAULT_LIMIT_EPSILON = 1e-6
_SOURCE_CONFIG = Path(__file__).resolve().parent.parent / "config"


@dataclass(frozen=True)
class JointLimit:
    min_position: float
    max_position: float
    max_velocity: float
    max_effort: float


@dataclass(frozen=True)
class Violation:
    kind: str
    message: str
    joint: str | None = None
    value: float | None = None
    bound: float | None = None
    point_index: int | None = None


class _LimitsLoader(yaml.SafeLoader):
    pass


def _degrees(loader: yaml.SafeLoader, node: yaml.Node) -> float:
    return math.radians(float(loader.construct_scalar(node)))


_LimitsLoader.add_constructor("!degrees", _degrees)


def _package_share(package: str) -> Path:
    try:
        from ament_index_python.packages import get_package_share_directory

        return Path(get_package_share_directory(package))
    except (ImportError, LookupError):
        fallback = Path("/opt/ros/jazzy/share") / package
        if fallback.is_dir():
            return fallback
        raise FileNotFoundError(f"could not locate ROS package share for {package!r}") from None


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def load_hard_limits(vendor_description_pkg: str, ur_type: str) -> dict[str, JointLimit]:
    """Load vendor limits dynamically, including UR's custom ``!degrees`` tag."""
    path = _package_share(vendor_description_pkg) / "config" / ur_type / "joint_limits.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"vendor joint limits not found: {path}")
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=_LimitsLoader) or {}
    raw_limits = data.get("joint_limits")
    if not isinstance(raw_limits, Mapping) or not raw_limits:
        raise ValueError(f"{path}: joint_limits must be a non-empty mapping")
    result: dict[str, JointLimit] = {}
    for joint, raw in raw_limits.items():
        if not isinstance(joint, str) or not isinstance(raw, Mapping):
            raise ValueError(f"{path}: malformed joint limit entry {joint!r}")
        required_flags = ("has_position_limits", "has_velocity_limits", "has_effort_limits")
        if any(raw.get(flag) is not True for flag in required_flags):
            raise ValueError(f"{path}: {joint} must declare position, velocity and effort limits")
        limit = JointLimit(
            min_position=_number(raw.get("min_position"), f"{joint}.min_position"),
            max_position=_number(raw.get("max_position"), f"{joint}.max_position"),
            max_velocity=_number(raw.get("max_velocity"), f"{joint}.max_velocity"),
            max_effort=_number(raw.get("max_effort"), f"{joint}.max_effort"),
        )
        if limit.min_position > limit.max_position or limit.max_velocity < 0 or limit.max_effort < 0:
            raise ValueError(f"{path}: invalid bounds for {joint}")
        result[joint] = limit
    return result


def _default_hard_limits() -> dict[str, JointLimit]:
    arm = load_arm_config()
    return load_hard_limits(arm.vendor_description_pkg, arm.ur_type)


def _default_override_path() -> Path:
    try:
        installed = _package_share("workbench_motion") / "config" / "joint_limits.hw_override.yaml"
        if installed.is_file():
            return installed
    except FileNotFoundError:
        pass
    return _SOURCE_CONFIG / "joint_limits.hw_override.yaml"


def load_hw_override(
    path: Path | str | None = None,
    *,
    hard_limits: Mapping[str, JointLimit] | None = None,
) -> dict[str, JointLimit]:
    """Load real-hardware overrides and reject anything not strictly within hard limits.

    An empty file or absent ``joint_limits`` mapping means no override. Missing
    joints are allowed; unknown joints, malformed values, and looser bounds are
    rejected fail-closed.
    """
    hard = dict(hard_limits or _default_hard_limits())
    override_path = Path(path) if path is not None else _default_override_path()
    if not override_path.is_file():
        raise FileNotFoundError(f"hardware override not found: {override_path}")
    data = yaml.safe_load(override_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, Mapping):
        raise ValueError("hardware override root must be a mapping")
    raw_limits = data.get("joint_limits")
    if raw_limits is None:
        return {}
    if not isinstance(raw_limits, Mapping):
        raise ValueError("hardware override joint_limits must be a mapping")
    result: dict[str, JointLimit] = {}
    allowed = {"min_position", "max_position", "max_velocity", "max_effort"}
    for joint, raw in raw_limits.items():
        if joint not in hard:
            raise ValueError(f"hardware override contains unknown joint {joint!r}")
        if not isinstance(raw, Mapping) or not raw:
            raise ValueError(f"hardware override for {joint} must be a non-empty mapping")
        unknown_keys = set(raw) - allowed
        if unknown_keys:
            raise ValueError(f"hardware override for {joint} has unknown fields: {sorted(unknown_keys)}")
        base = hard[joint]
        values = {
            "min_position": base.min_position,
            "max_position": base.max_position,
            "max_velocity": base.max_velocity,
            "max_effort": base.max_effort,
        }
        for key, value in raw.items():
            values[key] = _number(value, f"{joint}.{key}")
        candidate = JointLimit(**values)
        if candidate.min_position > candidate.max_position:
            raise ValueError(f"hardware override for {joint} has min_position > max_position")
        if candidate.max_velocity < 0 or candidate.max_effort < 0:
            raise ValueError(f"hardware override for {joint} has a negative magnitude")
        if (
            candidate.min_position < base.min_position
            or candidate.max_position > base.max_position
            or candidate.max_velocity > base.max_velocity
            or candidate.max_effort > base.max_effort
        ):
            raise ValueError(f"hardware override for {joint} is looser than the vendor hard limit")
        result[joint] = candidate
    return result


load_override = load_hw_override


def effective_limits(hard: Mapping[str, JointLimit], override: Mapping[str, JointLimit]) -> dict[str, JointLimit]:
    """Intersect hard and override limits, independently taking the tighter bound."""
    unknown = set(override) - set(hard)
    if unknown:
        raise ValueError(f"override contains unknown joints: {sorted(unknown)}")
    return {
        joint: JointLimit(
            min_position=max(base.min_position, override.get(joint, base).min_position),
            max_position=min(base.max_position, override.get(joint, base).max_position),
            max_velocity=min(base.max_velocity, override.get(joint, base).max_velocity),
            max_effort=min(base.max_effort, override.get(joint, base).max_effort),
        )
        for joint, base in hard.items()
    }


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _seconds(value: Any) -> float:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, Mapping):
        return float(value.get("sec", 0)) + float(value.get("nanosec", 0)) / 1e9
    return float(getattr(value, "sec", 0)) + float(getattr(value, "nanosec", 0)) / 1e9


def _bad(kind: str, message: str, **kwargs: Any) -> Violation:
    return Violation(kind=kind, message=message, **kwargs)


def check_trajectory(
    traj: Any,
    current_joint_positions: Mapping[str, float],
    limits: Mapping[str, JointLimit] | None = None,
    *,
    limit_epsilon: float = DEFAULT_LIMIT_EPSILON,
) -> Violation | None:
    """Return the first fail-closed violation, or ``None``; never mutate ``traj``.

    ``traj`` may be a ROS-like object or a plain mapping with ``joint_names`` and
    ``points``. Explicit limits make tests and later adapters deterministic; when
    omitted, the shipped vendor hard limits and hardware override are loaded.
    """
    if not math.isfinite(limit_epsilon) or limit_epsilon < 0:
        raise ValueError("limit_epsilon must be finite and non-negative")
    if limits is None:
        hard = _default_hard_limits()
        limits = effective_limits(hard, load_hw_override(hard_limits=hard))
    limits = dict(limits)
    names = list(_field(traj, "joint_names", []) or [])
    if not names:
        return _bad("joint_names", "joint_names must be non-empty")
    if len(names) != len(set(names)):
        return _bad("joint_names", "joint_names contains duplicates")
    unknown = set(names) - set(limits)
    if unknown:
        return _bad("joint_names", f"unknown joints: {sorted(unknown)}")
    if set(names) != set(limits):
        return _bad("joint_names", "partial joint goals are not allowed")
    if set(current_joint_positions) != set(limits):
        return _bad("current_state", "current state must contain exactly all controlled joints")
    current: dict[str, float] = {}
    for joint, raw in current_joint_positions.items():
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return _bad("non_finite", f"current state for {joint} is not numeric", joint=joint)
        if not math.isfinite(value):
            return _bad("non_finite", f"current state for {joint} is not finite", joint=joint, value=value)
        lim = limits[joint]
        lo, hi = lim.min_position + limit_epsilon, lim.max_position - limit_epsilon
        if value < lo or value > hi:
            return _bad(
                "current_position",
                f"current state for {joint} is outside limits",
                joint=joint,
                value=value,
                bound=lo if value < lo else hi,
            )
        current[joint] = value

    points = list(_field(traj, "points", []) or [])
    if not points:
        return _bad("points", "trajectory points must be non-empty")
    previous_time: float | None = None
    previous_positions: Sequence[float] | None = None
    n = len(names)
    for index, point in enumerate(points):
        positions = list(_field(point, "positions", []) or [])
        if len(positions) != n:
            return _bad("array_length", "positions length must match joint_names", point_index=index)
        arrays = {
            "velocities": list(_field(point, "velocities", []) or []),
            "accelerations": list(_field(point, "accelerations", []) or []),
            "effort": list(_field(point, "effort", []) or []),
        }
        for field_name, values in arrays.items():
            if len(values) not in (0, n):
                return _bad("array_length", f"{field_name} length must be zero or match joint_names", point_index=index)
        try:
            time_from_start = _seconds(_field(point, "time_from_start", 0.0))
            numeric_positions = [float(v) for v in positions]
            numeric_arrays = {key: [float(v) for v in values] for key, values in arrays.items()}
        except (TypeError, ValueError):
            return _bad("non_finite", "trajectory contains a non-numeric value", point_index=index)
        all_values = [time_from_start, *numeric_positions]
        for values in numeric_arrays.values():
            all_values.extend(values)
        if not all(math.isfinite(v) for v in all_values):
            return _bad("non_finite", "trajectory contains NaN or infinity", point_index=index)
        if time_from_start < 0:
            return _bad(
                "time", "time_from_start must be non-negative", value=time_from_start, bound=0.0, point_index=index
            )
        if previous_time is not None and time_from_start <= previous_time:
            return _bad(
                "time",
                "time_from_start must be strictly increasing",
                value=time_from_start,
                bound=previous_time,
                point_index=index,
            )

        for offset, joint in enumerate(names):
            lim = limits[joint]
            pos = numeric_positions[offset]
            lo = lim.min_position + limit_epsilon
            hi = lim.max_position - limit_epsilon
            vmax = max(0.0, lim.max_velocity - limit_epsilon)
            emax = max(0.0, lim.max_effort - limit_epsilon)
            if pos < lo or pos > hi:
                return _bad(
                    "position",
                    f"{joint} position is outside limits",
                    joint=joint,
                    value=pos,
                    bound=lo if pos < lo else hi,
                    point_index=index,
                )
            if numeric_arrays["velocities"] and abs(numeric_arrays["velocities"][offset]) > vmax:
                return _bad(
                    "velocity",
                    f"{joint} velocity exceeds limit",
                    joint=joint,
                    value=numeric_arrays["velocities"][offset],
                    bound=vmax,
                    point_index=index,
                )
            if numeric_arrays["effort"] and abs(numeric_arrays["effort"][offset]) > emax:
                return _bad(
                    "effort",
                    f"{joint} effort exceeds limit",
                    joint=joint,
                    value=numeric_arrays["effort"][offset],
                    bound=emax,
                    point_index=index,
                )
            if previous_positions is None:
                start = current[joint]
                dt = time_from_start
                if dt == 0.0:
                    if abs(pos - start) > limit_epsilon:
                        return _bad(
                            "initial_position",
                            f"{joint} first point at t=0 differs from current state",
                            joint=joint,
                            value=pos,
                            bound=start,
                            point_index=index,
                        )
                elif abs(pos - start) / dt > vmax:
                    return _bad(
                        "segment_velocity",
                        f"{joint} current-to-first mean velocity exceeds limit",
                        joint=joint,
                        value=abs(pos - start) / dt,
                        bound=vmax,
                        point_index=index,
                    )
            else:
                dt = time_from_start - previous_time  # positive by the check above
                mean_velocity = abs(pos - previous_positions[offset]) / dt
                if mean_velocity > vmax:
                    return _bad(
                        "segment_velocity",
                        f"{joint} segment mean velocity exceeds limit",
                        joint=joint,
                        value=mean_velocity,
                        bound=vmax,
                        point_index=index,
                    )
        previous_time = time_from_start
        previous_positions = numeric_positions
    return None
