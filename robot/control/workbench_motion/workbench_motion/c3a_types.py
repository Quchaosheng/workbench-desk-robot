"""ROS-free value objects for the C3a plan-only bridge."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from workbench_motion.joint_limits import AcceptedTrajectory, PreflightContext

_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


class PlanStatus(StrEnum):
    PLANNED = "planned"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class DiagnosticCode(StrEnum):
    READY = "ready"
    INVALID_PLAN_REQUEST = "invalid_plan_request"
    READINESS_UNAVAILABLE = "readiness_unavailable"
    READINESS_STALE = "readiness_stale"
    CONTEXT_MISMATCH = "context_mismatch"
    PLANNING_SERVER_UNAVAILABLE = "planning_server_unavailable"
    PLANNING_TIMEOUT = "planning_timeout"
    PLANNING_REJECTED = "planning_rejected"
    ADAPTER_ERROR = "adapter_error"
    EMPTY_PLAN = "empty_plan"
    TRAJECTORY_REJECTED = "trajectory_rejected"
    MATERIALIZATION_MISMATCH = "materialization_mismatch"


class C3aError(RuntimeError):
    def __init__(self, code: DiagnosticCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class PlanningServerUnavailable(C3aError):
    def __init__(self, message: str = "MoveGroup action server unavailable") -> None:
        super().__init__(DiagnosticCode.PLANNING_SERVER_UNAVAILABLE, message)


class PlanningTimedOut(C3aError):
    def __init__(self, message: str = "MoveGroup planning timed out") -> None:
        super().__init__(DiagnosticCode.PLANNING_TIMEOUT, message)


class PlanningAdapterError(C3aError):
    def __init__(self, message: str = "MoveGroup adapter failed") -> None:
        super().__init__(DiagnosticCode.ADAPTER_ERROR, message)


class ReadinessError(C3aError):
    pass


@dataclass(frozen=True, slots=True)
class Pose:
    x: float
    y: float
    z: float
    qx: float
    qy: float
    qz: float
    qw: float


@dataclass(frozen=True, slots=True)
class PosePlanGoal:
    frame_id: str
    pose: Pose
    tolerance_profile: str = "standard"


@dataclass(frozen=True, slots=True)
class GoalTolerance:
    position_m: float
    orientation_rad: float


@dataclass(frozen=True, slots=True)
class PlanningProfile:
    pipeline_id: str
    planner_id: str
    num_planning_attempts: int
    allowed_planning_time_s: float
    max_velocity_scaling_factor: float
    max_acceleration_scaling_factor: float


@dataclass(frozen=True, slots=True)
class ControllerIdentity:
    name: str
    joint_names: tuple[str, ...]
    command_interfaces: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TransformSnapshot:
    parent_frame: str
    child_frame: str
    translation: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    timestamp_ns: int


@dataclass(frozen=True, slots=True)
class ReadinessSnapshot:
    model: str
    planning_group: str
    planning_frame: str
    ik_tip_link: str
    joint_names: tuple[str, ...]
    current_joint_positions: tuple[tuple[str, float], ...]
    full_joint_positions: tuple[tuple[str, float], ...]
    joint_state_timestamp_ns: int
    joint_state_observed_at_ns: int
    transform: TransformSnapshot
    transform_observed_at_ns: int
    checked_at_ns: int
    max_age_ns: int
    joint_state_timestamp_clock_id: str
    transform_timestamp_clock_id: str
    joint_state_observation_clock_id: str
    transform_observation_clock_id: str
    checked_at_clock_id: str
    clock_proof_sha256: str
    controller: ControllerIdentity
    planning_profile: PlanningProfile
    preflight_context: PreflightContext
    component_hashes: tuple[tuple[str, str], ...]
    package_versions: tuple[tuple[str, str], ...]
    config_sha256: str
    readiness_sha256: str


@dataclass(frozen=True, slots=True)
class PlanningRequest:
    planning_group: str
    planning_frame: str
    ik_tip_link: str
    joint_names: tuple[str, ...]
    start_positions: tuple[float, ...]
    full_start_positions: tuple[tuple[str, float], ...]
    pose: Pose
    tolerance: GoalTolerance
    pipeline_id: str
    planner_id: str
    num_planning_attempts: int
    allowed_planning_time_s: float
    max_velocity_scaling_factor: float
    max_acceleration_scaling_factor: float
    planning_request_sha256: str


@dataclass(frozen=True, slots=True)
class PlanningResponse:
    moveit_error_code: int
    trajectory_start: tuple[tuple[str, float], ...]
    trajectory: Any
    multi_dof_joint_count: int = 0


@dataclass(frozen=True, slots=True)
class PlanOnlyResult:
    status: PlanStatus
    diagnostic_code: DiagnosticCode
    accepted_trajectory: AcceptedTrajectory | None
    planning_request_sha256: str | None
    config_sha256: str | None
    readiness_sha256: str | None
    clock_proof_sha256: str | None
    moveit_error_code: int | None = None
    preflight_reason_code: str | None = None
    execution_goal_count: int = 0

    def __post_init__(self) -> None:
        if self.execution_goal_count != 0:
            raise ValueError("C3a execution_goal_count must remain zero")
        if (self.status is PlanStatus.PLANNED) != (self.accepted_trajectory is not None):
            raise ValueError("only planned results may contain AcceptedTrajectory")


@dataclass(frozen=True, slots=True)
class ControllerTrajectoryPoint:
    positions: tuple[float, ...]
    velocities: tuple[float, ...]
    accelerations: tuple[float, ...]
    effort: tuple[float, ...]
    time_from_start_ns: int


@dataclass(frozen=True, slots=True)
class ControllerTrajectorySnapshot:
    controller_name: str
    joint_names: tuple[str, ...]
    points: tuple[ControllerTrajectoryPoint, ...]
    trajectory_sha256: str
    effective_limits_sha256: str
    context_sha256: str
    config_sha256: str


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) is not None


def finite_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(float(value))
