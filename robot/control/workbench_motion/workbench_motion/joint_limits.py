"""ROS-free, fail-closed trajectory preflight and hard-limit loading.

The module owns one validator implementation: :func:`preflight_trajectory`.
The Phase-2 :func:`check_trajectory` API is retained as a compatibility wrapper.
Nothing here clamps, repairs, dispatches, imports ROS, or emits events.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from workbench_motion.arm_config import load_arm_config

DEFAULT_LIMIT_EPSILON = 1e-6
_SOURCE_CONFIG = Path(__file__).resolve().parent.parent / "config"
_MISSING = object()
_NANOSECONDS_PER_SECOND = 1_000_000_000
_MIN_DURATION_SEC = -(2**31)
_MAX_DURATION_SEC = 2**31 - 1


class ReasonCode(StrEnum):
    """Stable machine codes for trajectory rejection; values are append-only."""

    JOINT_NAMES = "joint_names"
    CURRENT_STATE = "current_state"
    POINTS = "points"
    ARRAY_LENGTH = "array_length"
    NON_FINITE = "non_finite"
    TIME = "time"
    CURRENT_POSITION = "current_position"
    POSITION = "position"
    VELOCITY = "velocity"
    EFFORT = "effort"
    INITIAL_POSITION = "initial_position"
    SEGMENT_VELOCITY = "segment_velocity"
    JOINT_ORDER_MISMATCH = "joint_order_mismatch"
    TIMESTAMP_MALFORMED = "timestamp_malformed"
    DURATION_EXCEEDED = "duration_exceeded"
    START_STATE_DISCONTINUITY = "start_state_discontinuity"


class ConfigurationCode(StrEnum):
    INVALID_POLICY = "invalid_policy"
    INVALID_LIMITS = "invalid_limits"


class PreflightConfigurationError(ValueError):
    """A readiness/configuration failure, distinct from a trajectory violation."""

    def __init__(self, code: ConfigurationCode, message: str) -> None:
        self.code = code
        super().__init__(f"{code.value}: {message}")


@dataclass(frozen=True)
class JointLimit:
    min_position: float
    max_position: float
    max_velocity: float
    max_effort: float


@dataclass(frozen=True, slots=True)
class PreflightPolicy:
    version: str
    limit_epsilon: float
    max_duration_s: float
    max_start_state_delta_rad: float


@dataclass(frozen=True, slots=True)
class PreflightContext:
    expected_joint_names: tuple[str, ...]
    effective_limits: tuple[tuple[str, JointLimit], ...]
    policy: PreflightPolicy
    effective_limits_sha256: str
    context_sha256: str


@dataclass(frozen=True)
class Violation:
    # ``kind`` remains a real field so dataclasses.asdict retains the six-field
    # Phase-2 evidence shape. StrEnum remains JSON-serializable as a string.
    kind: ReasonCode
    message: str
    joint: str | None = None
    value: float | None = None
    bound: float | None = None
    point_index: int | None = None

    @property
    def code(self) -> ReasonCode:
        return self.kind


@dataclass(frozen=True, slots=True)
class NormalizedPoint:
    positions: tuple[float, ...]
    velocities: tuple[float, ...]
    accelerations: tuple[float, ...]
    effort: tuple[float, ...]
    time_from_start_ns: int


@dataclass(frozen=True, slots=True)
class NormalizedTrajectory:
    joint_names: tuple[str, ...]
    points: tuple[NormalizedPoint, ...]


@dataclass(frozen=True, slots=True, init=False)
class AcceptedTrajectory:
    """Deeply immutable accepted snapshot, constructible only by this module."""

    snapshot: NormalizedTrajectory
    canonical_bytes: bytes
    trajectory_sha256: str
    policy_version: str
    effective_limits_sha256: str
    context_sha256: str

    def __new__(cls):  # pragma: no cover - the public rejection is tested
        raise TypeError("AcceptedTrajectory can only be created by preflight_trajectory")


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
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label} must be a finite number") from exc
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


def _default_policy_path() -> Path:
    try:
        installed = _package_share("workbench_motion") / "config" / "trajectory_preflight.yaml"
        if installed.is_file():
            return installed
    except FileNotFoundError:
        pass
    return _SOURCE_CONFIG / "trajectory_preflight.yaml"


def load_hw_override(
    path: Path | str | None = None,
    *,
    hard_limits: Mapping[str, JointLimit] | None = None,
) -> dict[str, JointLimit]:
    """Load hardware overrides and reject anything outside vendor hard limits."""
    hard = dict(_default_hard_limits() if hard_limits is None else hard_limits)
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


def _validate_override_within_hard(hard: Mapping[str, JointLimit], override: Mapping[str, JointLimit]) -> None:
    unknown = set(override) - set(hard)
    if unknown:
        raise ValueError(f"override contains unknown joints: {sorted(unknown)}")
    for joint, candidate in override.items():
        if not isinstance(candidate, JointLimit):
            raise ValueError(f"override limit for {joint} must be JointLimit")
        values = (
            candidate.min_position,
            candidate.max_position,
            candidate.max_velocity,
            candidate.max_effort,
        )
        for value in values:
            _number(value, f"override limit for {joint}")
        if candidate.min_position > candidate.max_position:
            raise ValueError(f"override limit for {joint} has min_position > max_position")
        if candidate.max_velocity < 0 or candidate.max_effort < 0:
            raise ValueError(f"override limit for {joint} has a negative magnitude")
        base = hard[joint]
        if (
            candidate.min_position < base.min_position
            or candidate.max_position > base.max_position
            or candidate.max_velocity > base.max_velocity
            or candidate.max_effort > base.max_effort
        ):
            raise ValueError(f"override limit for {joint} is looser than the hard limit")


def effective_limits(hard: Mapping[str, JointLimit], override: Mapping[str, JointLimit]) -> dict[str, JointLimit]:
    """Intersect hard and override limits, independently taking tighter bounds."""
    _validate_override_within_hard(hard, override)
    return {
        joint: JointLimit(
            min_position=max(base.min_position, override.get(joint, base).min_position),
            max_position=min(base.max_position, override.get(joint, base).max_position),
            max_velocity=min(base.max_velocity, override.get(joint, base).max_velocity),
            max_effort=min(base.max_effort, override.get(joint, base).max_effort),
        )
        for joint, base in hard.items()
    }


def _policy_from_mapping(raw: Mapping[str, Any]) -> PreflightPolicy:
    expected = {"version", "limit_epsilon", "max_duration_s", "max_start_state_delta_rad"}
    if set(raw) != expected:
        missing = sorted(expected - set(raw))
        unknown = sorted(set(raw) - expected)
        raise ValueError(f"policy fields mismatch; missing={missing}, unknown={unknown}")
    version = raw["version"]
    if not isinstance(version, str) or not version:
        raise ValueError("policy version must be a non-empty string")
    return PreflightPolicy(
        version=version,
        limit_epsilon=_number(raw["limit_epsilon"], "limit_epsilon"),
        max_duration_s=_number(raw["max_duration_s"], "max_duration_s"),
        max_start_state_delta_rad=_number(raw["max_start_state_delta_rad"], "max_start_state_delta_rad"),
    )


def _duration_threshold_ns(seconds: float) -> int:
    try:
        nanoseconds = Decimal(str(seconds)) * _NANOSECONDS_PER_SECOND
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("duration must be exactly representable in nanoseconds") from exc
    if nanoseconds != nanoseconds.to_integral_value():
        raise ValueError("duration must be exactly representable in nanoseconds")
    return int(nanoseconds)


def _validate_policy(policy: PreflightPolicy) -> PreflightPolicy:
    if not isinstance(policy, PreflightPolicy):
        raise ValueError("policy must be PreflightPolicy or a policy mapping")
    if not isinstance(policy.version, str) or not policy.version:
        raise ValueError("policy version must be a non-empty string")
    epsilon = _number(policy.limit_epsilon, "limit_epsilon")
    duration = _number(policy.max_duration_s, "max_duration_s")
    start_delta = _number(policy.max_start_state_delta_rad, "max_start_state_delta_rad")
    if epsilon < 0:
        raise ValueError("limit_epsilon must be non-negative")
    if duration <= 0 or start_delta <= 0:
        raise ValueError("duration and start-state delta must be positive")
    _duration_threshold_ns(duration)
    return PreflightPolicy(policy.version, epsilon, duration, start_delta)


def load_preflight_policy(path: Path | str | None = None) -> PreflightPolicy:
    """Load and strictly validate the versioned preflight policy file."""
    policy_path = Path(path) if path is not None else _default_policy_path()
    try:
        data = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        if not isinstance(data, Mapping) or set(data) != {"trajectory_preflight"}:
            raise ValueError("policy root must contain only trajectory_preflight")
        raw = data["trajectory_preflight"]
        if not isinstance(raw, Mapping):
            raise ValueError("trajectory_preflight must be a mapping")
        return _validate_policy(_policy_from_mapping(raw))
    except PreflightConfigurationError:
        raise
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise PreflightConfigurationError(ConfigurationCode.INVALID_POLICY, str(exc)) from exc


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _limit_payload(expected: tuple[str, ...], limits: Mapping[str, JointLimit]) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "joint_limits": [
            {
                "joint": joint,
                "min_position": float(limits[joint].min_position).hex(),
                "max_position": float(limits[joint].max_position).hex(),
                "max_velocity": float(limits[joint].max_velocity).hex(),
                "max_effort": float(limits[joint].max_effort).hex(),
            }
            for joint in expected
        ],
    }


def _context_hashes(
    expected: tuple[str, ...], limits: Mapping[str, JointLimit], policy: PreflightPolicy
) -> tuple[str, str]:
    limits_hash = _sha256(_canonical_json_bytes(_limit_payload(expected, limits)))
    context_payload = {
        "schema_version": "1",
        "expected_joint_names": list(expected),
        "effective_limits_sha256": limits_hash,
        "policy": {
            "version": policy.version,
            "limit_epsilon": policy.limit_epsilon.hex(),
            "max_duration_s": policy.max_duration_s.hex(),
            "max_start_state_delta_rad": policy.max_start_state_delta_rad.hex(),
        },
    }
    return limits_hash, _sha256(_canonical_json_bytes(context_payload))


def _validate_limits(expected: tuple[str, ...], limits: Mapping[str, JointLimit], epsilon: float) -> None:
    if not expected or any(not isinstance(joint, str) or not joint for joint in expected):
        raise ValueError("expected joint names must be non-empty strings")
    if len(set(expected)) != len(expected):
        raise ValueError("expected joint names contain duplicates")
    if set(limits) != set(expected):
        raise ValueError("effective limits must contain exactly the expected joints")
    for joint in expected:
        limit = limits[joint]
        if not isinstance(limit, JointLimit):
            raise ValueError(f"limit for {joint} must be JointLimit")
        values = (limit.min_position, limit.max_position, limit.max_velocity, limit.max_effort)
        for value in values:
            _number(value, f"limit for {joint}")
        if limit.min_position > limit.max_position or limit.max_velocity < 0 or limit.max_effort < 0:
            raise ValueError(f"limit for {joint} has invalid bounds")
        if limit.min_position + epsilon > limit.max_position - epsilon:
            raise ValueError(f"limit epsilon collapses the position range for {joint}")


def build_preflight_context(
    *,
    policy: PreflightPolicy | Mapping[str, Any] | None = None,
    expected_joint_names: Sequence[str] | None = None,
    hard_limits: Mapping[str, JointLimit] | None = None,
    override_limits: Mapping[str, JointLimit] | None = None,
) -> PreflightContext:
    """Build an immutable readiness snapshot from controlled or explicit inputs."""
    try:
        if policy is None:
            validated_policy = load_preflight_policy()
        else:
            candidate = _policy_from_mapping(policy) if isinstance(policy, Mapping) else policy
            validated_policy = _validate_policy(candidate)
    except PreflightConfigurationError:
        raise
    except (TypeError, ValueError) as exc:
        raise PreflightConfigurationError(ConfigurationCode.INVALID_POLICY, str(exc)) from exc

    try:
        arm = None
        if expected_joint_names is None or hard_limits is None:
            arm = load_arm_config()
        expected = tuple(arm.joints if expected_joint_names is None else expected_joint_names)
        hard = load_hard_limits(arm.vendor_description_pkg, arm.ur_type) if hard_limits is None else dict(hard_limits)
        override = load_hw_override(hard_limits=hard) if override_limits is None else dict(override_limits)
        _validate_limits(expected, hard, validated_policy.limit_epsilon)
        combined = effective_limits(hard, override)
        _validate_limits(expected, combined, validated_policy.limit_epsilon)
        ordered = {joint: combined[joint] for joint in expected}
        limits_hash, context_hash = _context_hashes(expected, ordered, validated_policy)
        return PreflightContext(
            expected_joint_names=expected,
            effective_limits=tuple(ordered.items()),
            policy=validated_policy,
            effective_limits_sha256=limits_hash,
            context_sha256=context_hash,
        )
    except PreflightConfigurationError:
        raise
    except (AttributeError, KeyError, OSError, TypeError, ValueError) as exc:
        raise PreflightConfigurationError(ConfigurationCode.INVALID_LIMITS, str(exc)) from exc


def _validated_context(context: PreflightContext) -> tuple[tuple[str, ...], dict[str, JointLimit], PreflightPolicy]:
    if not isinstance(context, PreflightContext):
        raise PreflightConfigurationError(ConfigurationCode.INVALID_LIMITS, "context must be a PreflightContext")
    try:
        policy = _validate_policy(context.policy)
    except (AttributeError, TypeError, ValueError) as exc:
        raise PreflightConfigurationError(ConfigurationCode.INVALID_POLICY, str(exc)) from exc
    try:
        expected = tuple(context.expected_joint_names)
        limits = dict(context.effective_limits)
        if len(limits) != len(context.effective_limits):
            raise ValueError("effective limits contain duplicate joints")
        _validate_limits(expected, limits, policy.limit_epsilon)
        limits_hash, context_hash = _context_hashes(expected, limits, policy)
        if limits_hash != context.effective_limits_sha256 or context_hash != context.context_sha256:
            raise ValueError("context hashes do not match context contents")
        return expected, limits, policy
    except (TypeError, ValueError) as exc:
        raise PreflightConfigurationError(ConfigurationCode.INVALID_LIMITS, str(exc)) from exc


def _field(obj: Any, name: str, default: Any = None) -> Any:
    try:
        if isinstance(obj, Mapping):
            return obj.get(name, default)
        return getattr(obj, name, default)
    except (AttributeError, KeyError, TypeError, ValueError):
        return default


def _array(value: Any) -> tuple[Any, ...] | None:
    if value is None:
        return ()
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        try:
            return tuple(value)
        except (TypeError, ValueError):
            return None
    return None


def _bad(kind: ReasonCode, message: str, **kwargs: Any) -> Violation:
    return Violation(kind=kind, message=message, **kwargs)


def _numeric_array(values: tuple[Any, ...], index: int) -> tuple[float, ...] | Violation:
    result: list[float] = []
    for raw in values:
        if isinstance(raw, bool):
            return _bad(ReasonCode.NON_FINITE, "trajectory contains a non-numeric value", point_index=index)
        try:
            value = float(raw)
        except (OverflowError, TypeError, ValueError):
            return _bad(ReasonCode.NON_FINITE, "trajectory contains a non-numeric value", point_index=index)
        if not math.isfinite(value):
            return _bad(ReasonCode.NON_FINITE, "trajectory contains NaN or infinity", point_index=index)
        result.append(value)
    return tuple(result)


def _structured_time_ns(sec: Any, nanosec: Any, index: int) -> int | Violation:
    if (
        isinstance(sec, bool)
        or isinstance(nanosec, bool)
        or not isinstance(sec, int)
        or not isinstance(nanosec, int)
        or not (_MIN_DURATION_SEC <= sec <= _MAX_DURATION_SEC)
        or not (0 <= nanosec < _NANOSECONDS_PER_SECOND)
    ):
        return _bad(ReasonCode.TIMESTAMP_MALFORMED, "duration sec/nanosec fields are malformed", point_index=index)
    return sec * _NANOSECONDS_PER_SECOND + nanosec


def _time_ns(raw: Any, index: int) -> int | Violation:
    if raw is _MISSING or isinstance(raw, bool):
        return _bad(ReasonCode.TIMESTAMP_MALFORMED, "time_from_start is missing or malformed", point_index=index)
    if isinstance(raw, int | float):
        if isinstance(raw, int):
            return raw * _NANOSECONDS_PER_SECOND
        if isinstance(raw, float) and not math.isfinite(raw):
            return _bad(ReasonCode.NON_FINITE, "trajectory contains NaN or infinity", point_index=index)
        try:
            nanoseconds = Decimal(str(raw)) * _NANOSECONDS_PER_SECOND
        except (InvalidOperation, ValueError):
            return _bad(ReasonCode.TIMESTAMP_MALFORMED, "time is not representable in nanoseconds", point_index=index)
        if nanoseconds != nanoseconds.to_integral_value():
            return _bad(ReasonCode.TIMESTAMP_MALFORMED, "time is not representable in nanoseconds", point_index=index)
        return int(nanoseconds)
    if isinstance(raw, Mapping):
        if "sec" not in raw or "nanosec" not in raw:
            return _bad(ReasonCode.TIMESTAMP_MALFORMED, "duration requires sec and nanosec", point_index=index)
        return _structured_time_ns(raw["sec"], raw["nanosec"], index)
    sec = getattr(raw, "sec", _MISSING)
    nanosec = getattr(raw, "nanosec", _MISSING)
    if sec is _MISSING or nanosec is _MISSING:
        return _bad(ReasonCode.TIMESTAMP_MALFORMED, "duration requires sec and nanosec", point_index=index)
    return _structured_time_ns(sec, nanosec, index)


def _seconds_for_violation(timestamp_ns: int) -> float | None:
    try:
        return timestamp_ns / _NANOSECONDS_PER_SECOND
    except OverflowError:
        return None


def trajectory_canonical_bytes(snapshot: NormalizedTrajectory) -> bytes:
    """Return the single canonical representation used by all Motion stages."""
    return _canonical_json_bytes(
        {
            "schema_version": "1",
            "joint_names": list(snapshot.joint_names),
            "points": [
                {
                    "positions": [value.hex() for value in point.positions],
                    "velocities": [value.hex() for value in point.velocities],
                    "accelerations": [value.hex() for value in point.accelerations],
                    "effort": [value.hex() for value in point.effort],
                    "time_from_start_ns": point.time_from_start_ns,
                }
                for point in snapshot.points
            ],
        }
    )


def _accept(snapshot: NormalizedTrajectory, context: PreflightContext) -> AcceptedTrajectory:
    canonical = trajectory_canonical_bytes(snapshot)
    accepted = object.__new__(AcceptedTrajectory)
    object.__setattr__(accepted, "snapshot", snapshot)
    object.__setattr__(accepted, "canonical_bytes", canonical)
    object.__setattr__(accepted, "trajectory_sha256", _sha256(canonical))
    object.__setattr__(accepted, "policy_version", context.policy.version)
    object.__setattr__(accepted, "effective_limits_sha256", context.effective_limits_sha256)
    object.__setattr__(accepted, "context_sha256", context.context_sha256)
    return accepted


def preflight_trajectory(
    traj: Any,
    current_joint_positions: Mapping[str, float],
    *,
    context: PreflightContext,
) -> AcceptedTrajectory | Violation:
    """Return an immutable accepted snapshot or the first stable violation."""
    expected, limits, policy = _validated_context(context)

    raw_names = _array(_field(traj, "joint_names", _MISSING))
    if raw_names is None or not raw_names or any(not isinstance(name, str) or not name for name in raw_names):
        return _bad(ReasonCode.JOINT_NAMES, "joint_names must be non-empty strings")
    names = tuple(raw_names)
    if len(names) != len(set(names)):
        return _bad(ReasonCode.JOINT_NAMES, "joint_names contains duplicates")
    if set(names) != set(expected):
        return _bad(ReasonCode.JOINT_NAMES, "joint_names must contain exactly all controlled joints")
    if names != expected:
        return _bad(ReasonCode.JOINT_ORDER_MISMATCH, "joint_names order does not match the controlled order")

    if not isinstance(current_joint_positions, Mapping) or set(current_joint_positions) != set(expected):
        return _bad(ReasonCode.CURRENT_STATE, "current state must contain exactly all controlled joints")
    current: dict[str, float] = {}
    epsilon = policy.limit_epsilon
    for joint in expected:
        raw = current_joint_positions[joint]
        if isinstance(raw, bool):
            return _bad(ReasonCode.NON_FINITE, f"current state for {joint} is not numeric", joint=joint)
        try:
            value = float(raw)
        except (OverflowError, TypeError, ValueError):
            return _bad(ReasonCode.NON_FINITE, f"current state for {joint} is not numeric", joint=joint)
        if not math.isfinite(value):
            return _bad(ReasonCode.NON_FINITE, f"current state for {joint} is not finite", joint=joint, value=value)
        current[joint] = value

    for joint in expected:
        value = current[joint]
        limit = limits[joint]
        lo, hi = limit.min_position + epsilon, limit.max_position - epsilon
        if value < lo or value > hi:
            return _bad(
                ReasonCode.CURRENT_POSITION,
                f"current state for {joint} is outside limits",
                joint=joint,
                value=value,
                bound=lo if value < lo else hi,
            )

    raw_points = _array(_field(traj, "points", _MISSING))
    if raw_points is None or not raw_points:
        return _bad(ReasonCode.POINTS, "trajectory points must be non-empty")
    raw_arrays: list[dict[str, tuple[Any, ...]]] = []
    size = len(expected)
    for index, point in enumerate(raw_points):
        fields: dict[str, tuple[Any, ...]] = {}
        for field_name in ("positions", "velocities", "accelerations", "effort"):
            values = _array(_field(point, field_name, _MISSING if field_name == "positions" else ()))
            valid_lengths = (size,) if field_name == "positions" else (0, size)
            if values is None or len(values) not in valid_lengths:
                length_requirement = (
                    "match joint_names" if field_name == "positions" else "be zero or match joint_names"
                )
                return _bad(
                    ReasonCode.ARRAY_LENGTH,
                    f"{field_name} length must {length_requirement}",
                    point_index=index,
                )
            fields[field_name] = values
        raw_arrays.append(fields)

    parsed_arrays: list[dict[str, tuple[float, ...]]] = []
    for index, fields in enumerate(raw_arrays):
        parsed: dict[str, tuple[float, ...]] = {}
        for field_name, values in fields.items():
            numeric = _numeric_array(values, index)
            if isinstance(numeric, Violation):
                return numeric
            parsed[field_name] = numeric
        parsed_arrays.append(parsed)

    for index, point in enumerate(raw_points):
        raw_time = _field(point, "time_from_start", _MISSING)
        if isinstance(raw_time, float) and not math.isfinite(raw_time):
            return _bad(ReasonCode.NON_FINITE, "trajectory contains NaN or infinity", point_index=index)

    normalized_points: list[NormalizedPoint] = []
    for index, (point, parsed) in enumerate(zip(raw_points, parsed_arrays, strict=True)):
        timestamp = _time_ns(_field(point, "time_from_start", _MISSING), index)
        if isinstance(timestamp, Violation):
            return timestamp
        normalized_points.append(
            NormalizedPoint(
                positions=parsed["positions"],
                velocities=parsed["velocities"],
                accelerations=parsed["accelerations"],
                effort=parsed["effort"],
                time_from_start_ns=timestamp,
            )
        )

    for index, point in enumerate(normalized_points):
        timestamp = point.time_from_start_ns
        if timestamp < 0:
            return _bad(
                ReasonCode.TIME,
                "time_from_start must be non-negative",
                value=_seconds_for_violation(timestamp),
                bound=0.0,
                point_index=index,
            )

    previous_ns = normalized_points[0].time_from_start_ns
    for index, point in enumerate(normalized_points[1:], start=1):
        timestamp = point.time_from_start_ns
        if timestamp <= previous_ns:
            return _bad(
                ReasonCode.TIME,
                "time_from_start must be strictly increasing",
                value=_seconds_for_violation(timestamp),
                bound=_seconds_for_violation(previous_ns),
                point_index=index,
            )
        previous_ns = timestamp

    max_duration_ns = _duration_threshold_ns(policy.max_duration_s)
    final_index = len(normalized_points) - 1
    final_timestamp = normalized_points[final_index].time_from_start_ns
    if final_timestamp > max_duration_ns:
        return _bad(
            ReasonCode.DURATION_EXCEEDED,
            "trajectory duration exceeds policy",
            value=_seconds_for_violation(final_timestamp),
            bound=policy.max_duration_s,
            point_index=final_index,
        )

    for index, point in enumerate(normalized_points):
        for offset, joint in enumerate(expected):
            limit = limits[joint]
            position = point.positions[offset]
            lo = limit.min_position + epsilon
            hi = limit.max_position - epsilon
            vmax = max(0.0, limit.max_velocity - epsilon)
            emax = max(0.0, limit.max_effort - epsilon)
            if position < lo or position > hi:
                return _bad(
                    ReasonCode.POSITION,
                    f"{joint} position is outside limits",
                    joint=joint,
                    value=position,
                    bound=lo if position < lo else hi,
                    point_index=index,
                )
            if point.velocities and abs(point.velocities[offset]) > vmax:
                return _bad(
                    ReasonCode.VELOCITY,
                    f"{joint} velocity exceeds limit",
                    joint=joint,
                    value=point.velocities[offset],
                    bound=vmax,
                    point_index=index,
                )
            if point.effort and abs(point.effort[offset]) > emax:
                return _bad(
                    ReasonCode.EFFORT,
                    f"{joint} effort exceeds limit",
                    joint=joint,
                    value=point.effort[offset],
                    bound=emax,
                    point_index=index,
                )

    first = normalized_points[0]
    for offset, joint in enumerate(expected):
        delta = abs(first.positions[offset] - current[joint])
        if first.time_from_start_ns == 0:
            if delta > epsilon:
                return _bad(
                    ReasonCode.INITIAL_POSITION,
                    f"{joint} first point at t=0 differs from current state",
                    joint=joint,
                    value=first.positions[offset],
                    bound=current[joint],
                    point_index=0,
                )
        elif delta > policy.max_start_state_delta_rad:
            return _bad(
                ReasonCode.START_STATE_DISCONTINUITY,
                f"{joint} first point is too far from current state",
                joint=joint,
                value=delta,
                bound=policy.max_start_state_delta_rad,
                point_index=0,
            )

    previous_positions: tuple[float, ...] | None = None
    previous_time_ns: int | None = None
    for index, point in enumerate(normalized_points):
        for offset, joint in enumerate(expected):
            if previous_positions is None:
                if point.time_from_start_ns == 0:
                    continue
                start = current[joint]
                delta = abs(point.positions[offset] - start)
                dt_ns = point.time_from_start_ns
                message = f"{joint} current-to-first mean velocity exceeds limit"
            else:
                delta = abs(point.positions[offset] - previous_positions[offset])
                dt_ns = point.time_from_start_ns - previous_time_ns
                message = f"{joint} segment mean velocity exceeds limit"
            mean_velocity = delta * _NANOSECONDS_PER_SECOND / dt_ns
            vmax = max(0.0, limits[joint].max_velocity - epsilon)
            if mean_velocity > vmax:
                return _bad(
                    ReasonCode.SEGMENT_VELOCITY,
                    message,
                    joint=joint,
                    value=mean_velocity,
                    bound=vmax,
                    point_index=index,
                )
        previous_positions = point.positions
        previous_time_ns = point.time_from_start_ns

    snapshot = NormalizedTrajectory(joint_names=expected, points=tuple(normalized_points))
    return _accept(snapshot, context)


def check_trajectory(
    traj: Any,
    current_joint_positions: Mapping[str, float],
    limits: Mapping[str, JointLimit] | None = None,
    *,
    limit_epsilon: float = DEFAULT_LIMIT_EPSILON,
) -> Violation | None:
    """Compatibility wrapper returning ``Violation | None`` without mutation."""
    try:
        epsilon = _number(limit_epsilon, "limit_epsilon")
    except ValueError as exc:
        raise ValueError("limit_epsilon must be finite and non-negative") from exc
    if epsilon < 0:
        raise ValueError("limit_epsilon must be finite and non-negative")
    policy = replace(load_preflight_policy(), limit_epsilon=epsilon)
    if limits is None:
        context = build_preflight_context(policy=policy)
    else:
        supplied_limits = dict(limits)
        context = build_preflight_context(
            policy=policy,
            expected_joint_names=tuple(supplied_limits),
            hard_limits=supplied_limits,
            override_limits={},
        )
    result = preflight_trajectory(traj, current_joint_positions, context=context)
    return result if isinstance(result, Violation) else None
