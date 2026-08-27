"""Deep, ROS-free C3a module for plan-only MoveIt orchestration."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from workbench_motion.c3a_types import (
    C3aError,
    ControllerIdentity,
    ControllerTrajectoryPoint,
    ControllerTrajectorySnapshot,
    DiagnosticCode,
    GoalTolerance,
    PlanningAdapterError,
    PlanningProfile,
    PlanningRequest,
    PlanningResponse,
    PlanOnlyResult,
    PlanStatus,
    Pose,
    PosePlanGoal,
    ReadinessError,
    ReadinessSnapshot,
    canonical_json_bytes,
    finite_number,
    sha256_bytes,
    valid_sha256,
)
from workbench_motion.joint_limits import AcceptedTrajectory, Violation, preflight_trajectory

_TOLERANCE_PROFILES = {"standard": GoalTolerance(position_m=0.005, orientation_rad=0.05)}
_MOVEIT_SUCCESS = 1
_REQUIRED_COMPONENT_HASHES = {
    "robot_description",
    "arm.yaml",
    "workbench_arm.srdf",
    "kinematics.yaml",
    "ompl_planning.yaml",
    "moveit_joint_limits.yaml",
    "controllers.yaml",
    "trajectory_preflight.yaml",
    "joint_limits.hw_override.yaml",
}


class PlanningPort(Protocol):
    def plan_only(self, request: PlanningRequest) -> PlanningResponse: ...


class ReadinessPort(Protocol):
    def snapshot(self) -> ReadinessSnapshot: ...

    def configuration_sha256(self) -> str: ...


class InMemoryPlanningAdapter:
    def __init__(
        self,
        response: PlanningResponse | Callable[[PlanningRequest], PlanningResponse],
    ) -> None:
        self._response = response
        self.requests: list[PlanningRequest] = []

    def plan_only(self, request: PlanningRequest) -> PlanningResponse:
        self.requests.append(request)
        if callable(self._response):
            return self._response(request)
        return self._response


class InMemoryReadinessAdapter:
    def __init__(
        self,
        snapshot: ReadinessSnapshot | Callable[[], ReadinessSnapshot],
    ) -> None:
        self._snapshot = snapshot
        self.calls = 0

    def snapshot(self) -> ReadinessSnapshot:
        self.calls += 1
        if callable(self._snapshot):
            return self._snapshot()
        return self._snapshot

    def configuration_sha256(self) -> str:
        return validate_readiness(self.snapshot()).config_sha256


def _float_hex(value: float) -> str:
    return float(value).hex()


def _ordered_pairs(values: tuple[tuple[str, object], ...], label: str) -> dict[str, object]:
    try:
        result = dict(values)
    except (TypeError, ValueError) as exc:
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, f"{label} is malformed") from exc
    if len(result) != len(values):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, f"{label} contains duplicates")
    return result


def _config_payload(snapshot: ReadinessSnapshot) -> dict[str, object]:
    return {
        "schema_version": "c3a-config-1",
        "arm": {
            "model": snapshot.model,
            "planning_group": snapshot.planning_group,
            "planning_frame": snapshot.planning_frame,
            "ik_tip_link": snapshot.ik_tip_link,
            "joint_names": list(snapshot.joint_names),
        },
        "controller": {
            "name": snapshot.controller.name,
            "joint_names": list(snapshot.controller.joint_names),
            "command_interfaces": list(snapshot.controller.command_interfaces),
        },
        "planning_profile": {
            "pipeline_id": snapshot.planning_profile.pipeline_id,
            "planner_id": snapshot.planning_profile.planner_id,
            "num_planning_attempts": snapshot.planning_profile.num_planning_attempts,
            "allowed_planning_time_s": _float_hex(snapshot.planning_profile.allowed_planning_time_s),
            "max_velocity_scaling_factor": _float_hex(snapshot.planning_profile.max_velocity_scaling_factor),
            "max_acceleration_scaling_factor": _float_hex(snapshot.planning_profile.max_acceleration_scaling_factor),
        },
        "preflight": {
            "policy_version": snapshot.preflight_context.policy.version,
            "effective_limits_sha256": snapshot.preflight_context.effective_limits_sha256,
            "context_sha256": snapshot.preflight_context.context_sha256,
        },
        "component_hashes": dict(snapshot.component_hashes),
        "package_versions": dict(snapshot.package_versions),
        "tolerance_profiles": {
            name: {
                "position_m": _float_hex(profile.position_m),
                "orientation_rad": _float_hex(profile.orientation_rad),
            }
            for name, profile in sorted(_TOLERANCE_PROFILES.items())
        },
    }


def _readiness_payload(snapshot: ReadinessSnapshot, config_sha256: str) -> dict[str, object]:
    return {
        "schema_version": "c3a-readiness-1",
        "config_sha256": config_sha256,
        "joint_state_timestamp_clock_id": snapshot.joint_state_timestamp_clock_id,
        "transform_timestamp_clock_id": snapshot.transform_timestamp_clock_id,
        "joint_state_observation_clock_id": snapshot.joint_state_observation_clock_id,
        "transform_observation_clock_id": snapshot.transform_observation_clock_id,
        "checked_at_clock_id": snapshot.checked_at_clock_id,
        "clock_proof_sha256": snapshot.clock_proof_sha256,
        "checked_at_ns": snapshot.checked_at_ns,
        "max_age_ns": snapshot.max_age_ns,
        "joint_state": {
            "timestamp_ns": snapshot.joint_state_timestamp_ns,
            "observed_at_ns": snapshot.joint_state_observed_at_ns,
            "positions": [[joint, _float_hex(value)] for joint, value in snapshot.current_joint_positions],
            "full_positions": [[joint, _float_hex(value)] for joint, value in snapshot.full_joint_positions],
        },
        "transform": {
            "parent_frame": snapshot.transform.parent_frame,
            "child_frame": snapshot.transform.child_frame,
            "timestamp_ns": snapshot.transform.timestamp_ns,
            "observed_at_ns": snapshot.transform_observed_at_ns,
            "translation": [_float_hex(value) for value in snapshot.transform.translation],
            "rotation": [_float_hex(value) for value in snapshot.transform.rotation],
        },
    }


def seal_readiness(snapshot: ReadinessSnapshot) -> ReadinessSnapshot:
    provisional = replace(snapshot, config_sha256="", readiness_sha256="")
    config_sha256 = sha256_bytes(canonical_json_bytes(_config_payload(provisional)))
    readiness_sha256 = sha256_bytes(canonical_json_bytes(_readiness_payload(provisional, config_sha256)))
    return replace(provisional, config_sha256=config_sha256, readiness_sha256=readiness_sha256)


def validate_readiness(snapshot: object) -> ReadinessSnapshot:
    if not isinstance(snapshot, ReadinessSnapshot):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "readiness snapshot has wrong type")
    text_fields = (
        snapshot.model,
        snapshot.planning_group,
        snapshot.planning_frame,
        snapshot.ik_tip_link,
        snapshot.joint_state_timestamp_clock_id,
        snapshot.transform_timestamp_clock_id,
        snapshot.joint_state_observation_clock_id,
        snapshot.transform_observation_clock_id,
        snapshot.checked_at_clock_id,
        snapshot.clock_proof_sha256,
    )
    if any(not isinstance(value, str) or not value for value in text_fields):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "readiness identity is incomplete")
    if not valid_sha256(snapshot.clock_proof_sha256):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "readiness clock proof is missing")
    if not (
        snapshot.joint_state_timestamp_clock_id
        == snapshot.transform_timestamp_clock_id
        == snapshot.joint_state_observation_clock_id
        == snapshot.transform_observation_clock_id
        == snapshot.checked_at_clock_id
    ):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "readiness clock provenance is not comparable")
    if (
        not snapshot.joint_names
        or len(set(snapshot.joint_names)) != len(snapshot.joint_names)
        or any(not isinstance(name, str) or not name for name in snapshot.joint_names)
    ):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "joint identity is incomplete")
    if snapshot.preflight_context.expected_joint_names != snapshot.joint_names:
        raise ReadinessError(DiagnosticCode.CONTEXT_MISMATCH, "preflight joint identity mismatch")
    current = _ordered_pairs(snapshot.current_joint_positions, "current joint state")
    if tuple(current) != snapshot.joint_names or any(not finite_number(value) for value in current.values()):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "current joint state is incomplete")
    full_current = _ordered_pairs(snapshot.full_joint_positions, "full current joint state")
    if any(not finite_number(value) for value in full_current.values()) or any(
        full_current.get(joint) != value for joint, value in current.items()
    ):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "full current joint state is incomplete")
    if not isinstance(snapshot.controller, ControllerIdentity):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "controller identity is missing")
    if (
        snapshot.controller.joint_names != snapshot.joint_names
        or snapshot.controller.command_interfaces != ("position",)
        or not snapshot.controller.name
    ):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "controller configuration mismatch")
    profile = snapshot.planning_profile
    if (
        not isinstance(profile, PlanningProfile)
        or not profile.pipeline_id
        or not isinstance(profile.planner_id, str)
        or isinstance(profile.num_planning_attempts, bool)
        or not isinstance(profile.num_planning_attempts, int)
        or profile.num_planning_attempts <= 0
        or not finite_number(profile.allowed_planning_time_s)
        or profile.allowed_planning_time_s <= 0
        or not finite_number(profile.max_velocity_scaling_factor)
        or not 0 < profile.max_velocity_scaling_factor <= 1
        or not finite_number(profile.max_acceleration_scaling_factor)
        or not 0 < profile.max_acceleration_scaling_factor <= 1
    ):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "planning profile is invalid")
    components = _ordered_pairs(snapshot.component_hashes, "component hashes")
    if set(components) != _REQUIRED_COMPONENT_HASHES or any(not valid_sha256(value) for value in components.values()):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "component hashes are incomplete")
    versions = _ordered_pairs(snapshot.package_versions, "package versions")
    if not versions or any(not isinstance(value, str) or not value for value in versions.values()):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "package versions are incomplete")
    if (
        snapshot.transform.parent_frame != snapshot.planning_frame
        or snapshot.transform.child_frame != snapshot.ik_tip_link
        or len(snapshot.transform.translation) != 3
        or len(snapshot.transform.rotation) != 4
        or any(not finite_number(value) for value in (*snapshot.transform.translation, *snapshot.transform.rotation))
    ):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "TF readiness is incomplete")
    quaternion_norm = math.sqrt(sum(value * value for value in snapshot.transform.rotation))
    if not math.isclose(quaternion_norm, 1.0, rel_tol=0.0, abs_tol=1e-6):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "TF quaternion is not normalized")
    integer_times = (
        snapshot.joint_state_timestamp_ns,
        snapshot.transform.timestamp_ns,
        snapshot.joint_state_observed_at_ns,
        snapshot.transform_observed_at_ns,
        snapshot.checked_at_ns,
        snapshot.max_age_ns,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in integer_times):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "readiness timestamps are malformed")
    if snapshot.max_age_ns <= 0 or min(integer_times[:-1]) < 0:
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "readiness timestamps are invalid")
    if (
        snapshot.checked_at_ns - snapshot.joint_state_timestamp_ns > snapshot.max_age_ns
        or snapshot.checked_at_ns - snapshot.transform.timestamp_ns > snapshot.max_age_ns
        or snapshot.joint_state_timestamp_ns > snapshot.checked_at_ns
        or snapshot.transform.timestamp_ns > snapshot.checked_at_ns
        or snapshot.checked_at_ns - snapshot.joint_state_observed_at_ns > snapshot.max_age_ns
        or snapshot.checked_at_ns - snapshot.transform_observed_at_ns > snapshot.max_age_ns
        or snapshot.joint_state_observed_at_ns > snapshot.checked_at_ns
        or snapshot.transform_observed_at_ns > snapshot.checked_at_ns
    ):
        raise ReadinessError(DiagnosticCode.READINESS_STALE, "joint-state or TF source/observation readiness is stale")
    sealed = seal_readiness(snapshot)
    if snapshot.config_sha256 != sealed.config_sha256 or snapshot.readiness_sha256 != sealed.readiness_sha256:
        raise ReadinessError(DiagnosticCode.CONTEXT_MISMATCH, "readiness hashes do not match contents")
    return snapshot


def _validate_goal(goal: object, readiness: ReadinessSnapshot) -> tuple[PosePlanGoal, GoalTolerance]:
    if type(goal) is not PosePlanGoal or type(goal.pose) is not Pose:
        raise C3aError(DiagnosticCode.INVALID_PLAN_REQUEST, "goal must be PosePlanGoal")
    if goal.frame_id != readiness.planning_frame or goal.tolerance_profile not in _TOLERANCE_PROFILES:
        raise C3aError(DiagnosticCode.INVALID_PLAN_REQUEST, "goal frame or tolerance profile is not allowed")
    values = (goal.pose.x, goal.pose.y, goal.pose.z, goal.pose.qx, goal.pose.qy, goal.pose.qz, goal.pose.qw)
    if any(not finite_number(value) for value in values):
        raise C3aError(DiagnosticCode.INVALID_PLAN_REQUEST, "goal pose must contain finite numbers")
    norm = math.sqrt(sum(value * value for value in values[3:]))
    if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-6):
        raise C3aError(DiagnosticCode.INVALID_PLAN_REQUEST, "goal quaternion must be normalized")
    return goal, _TOLERANCE_PROFILES[goal.tolerance_profile]


def _planning_request(
    goal: PosePlanGoal,
    tolerance: GoalTolerance,
    readiness: ReadinessSnapshot,
) -> PlanningRequest:
    current = dict(readiness.current_joint_positions)
    payload = {
        "schema_version": "c3a-planning-request-1",
        "planning_group": readiness.planning_group,
        "planning_frame": readiness.planning_frame,
        "ik_tip_link": readiness.ik_tip_link,
        "joint_names": list(readiness.joint_names),
        "start_positions": [_float_hex(current[joint]) for joint in readiness.joint_names],
        "full_start_positions": [[joint, _float_hex(value)] for joint, value in readiness.full_joint_positions],
        "pose": {field: _float_hex(getattr(goal.pose, field)) for field in goal.pose.__dataclass_fields__},
        "tolerance": {
            "position_m": _float_hex(tolerance.position_m),
            "orientation_rad": _float_hex(tolerance.orientation_rad),
        },
        "pipeline_id": readiness.planning_profile.pipeline_id,
        "planner_id": readiness.planning_profile.planner_id,
        "num_planning_attempts": readiness.planning_profile.num_planning_attempts,
        "allowed_planning_time_s": _float_hex(readiness.planning_profile.allowed_planning_time_s),
        "max_velocity_scaling_factor": _float_hex(readiness.planning_profile.max_velocity_scaling_factor),
        "max_acceleration_scaling_factor": _float_hex(readiness.planning_profile.max_acceleration_scaling_factor),
        "config_sha256": readiness.config_sha256,
        "readiness_sha256": readiness.readiness_sha256,
    }
    request_hash = sha256_bytes(canonical_json_bytes(payload))
    return PlanningRequest(
        planning_group=readiness.planning_group,
        planning_frame=readiness.planning_frame,
        ik_tip_link=readiness.ik_tip_link,
        joint_names=readiness.joint_names,
        start_positions=tuple(current[joint] for joint in readiness.joint_names),
        full_start_positions=readiness.full_joint_positions,
        pose=goal.pose,
        tolerance=tolerance,
        pipeline_id=readiness.planning_profile.pipeline_id,
        planner_id=readiness.planning_profile.planner_id,
        num_planning_attempts=readiness.planning_profile.num_planning_attempts,
        allowed_planning_time_s=readiness.planning_profile.allowed_planning_time_s,
        max_velocity_scaling_factor=readiness.planning_profile.max_velocity_scaling_factor,
        max_acceleration_scaling_factor=readiness.planning_profile.max_acceleration_scaling_factor,
        planning_request_sha256=request_hash,
    )


def _project_start(response: PlanningResponse, request: PlanningRequest) -> tuple[float, ...] | None:
    try:
        names = [name for name, _value in response.trajectory_start]
        if len(names) != len(set(names)) or any(not isinstance(name, str) or not name for name in names):
            return None
        expected_names = tuple(joint for joint, _value in request.full_start_positions)
        if tuple(names) != expected_names:
            return None
        values = dict(response.trajectory_start)
        if len(values) != len(expected_names) or any(not finite_number(values[joint]) for joint in expected_names):
            return None
        if tuple(float(values[joint]) for joint in expected_names) != tuple(
            value for _joint, value in request.full_start_positions
        ):
            return None
        return tuple(float(values[joint]) for joint in request.joint_names)
    except (TypeError, ValueError):
        return None


def _failure(
    status: PlanStatus,
    code: DiagnosticCode,
    readiness: ReadinessSnapshot | None = None,
    request: PlanningRequest | None = None,
    *,
    moveit_error_code: int | None = None,
    preflight_reason_code: str | None = None,
) -> PlanOnlyResult:
    return PlanOnlyResult(
        status=status,
        diagnostic_code=code,
        accepted_trajectory=None,
        planning_request_sha256=None if request is None else request.planning_request_sha256,
        config_sha256=None if readiness is None else readiness.config_sha256,
        readiness_sha256=None if readiness is None else readiness.readiness_sha256,
        clock_proof_sha256=None if readiness is None else readiness.clock_proof_sha256,
        moveit_error_code=moveit_error_code,
        preflight_reason_code=preflight_reason_code,
    )


class C3aPlanOnlyBridge:
    def __init__(self, planning: PlanningPort, readiness: ReadinessPort) -> None:
        self._planning = planning
        self._readiness = readiness
        self._accepted_bindings: dict[int, tuple[AcceptedTrajectory, ReadinessSnapshot]] = {}

    def plan(self, goal: PosePlanGoal) -> PlanOnlyResult:
        readiness: ReadinessSnapshot | None = None
        request: PlanningRequest | None = None
        try:
            readiness = validate_readiness(self._readiness.snapshot())
            validated_goal, tolerance = _validate_goal(goal, readiness)
            request = _planning_request(validated_goal, tolerance, readiness)
            response = self._planning.plan_only(request)
            if not isinstance(response, PlanningResponse):
                raise PlanningAdapterError("planning adapter returned the wrong type")
            if isinstance(response.moveit_error_code, bool) or not isinstance(response.moveit_error_code, int):
                raise PlanningAdapterError("MoveIt error code must be an integer")
            if isinstance(response.multi_dof_joint_count, bool) or not isinstance(response.multi_dof_joint_count, int):
                raise PlanningAdapterError("multi-DOF joint count must be an integer")
            if response.moveit_error_code != _MOVEIT_SUCCESS:
                return _failure(
                    PlanStatus.REJECTED,
                    DiagnosticCode.PLANNING_REJECTED,
                    readiness,
                    request,
                    moveit_error_code=response.moveit_error_code,
                )
            if response.multi_dof_joint_count != 0:
                return _failure(PlanStatus.REJECTED, DiagnosticCode.TRAJECTORY_REJECTED, readiness, request)
            projected_start = _project_start(response, request)
            if projected_start != request.start_positions:
                return _failure(PlanStatus.REJECTED, DiagnosticCode.CONTEXT_MISMATCH, readiness, request)
            if response.trajectory is None:
                return _failure(PlanStatus.REJECTED, DiagnosticCode.EMPTY_PLAN, readiness, request)
            current = dict(readiness.current_joint_positions)
            accepted = preflight_trajectory(
                response.trajectory,
                current,
                context=readiness.preflight_context,
            )
            if isinstance(accepted, Violation):
                return _failure(
                    PlanStatus.REJECTED,
                    DiagnosticCode.TRAJECTORY_REJECTED,
                    readiness,
                    request,
                    preflight_reason_code=accepted.kind.value,
                )
            self._accepted_bindings[id(accepted)] = (accepted, readiness)
            return PlanOnlyResult(
                status=PlanStatus.PLANNED,
                diagnostic_code=DiagnosticCode.READY,
                accepted_trajectory=accepted,
                planning_request_sha256=request.planning_request_sha256,
                config_sha256=readiness.config_sha256,
                readiness_sha256=readiness.readiness_sha256,
                clock_proof_sha256=readiness.clock_proof_sha256,
                moveit_error_code=response.moveit_error_code,
            )
        except ReadinessError as exc:
            return _failure(PlanStatus.UNAVAILABLE, exc.code, readiness, request)
        except C3aError as exc:
            status = (
                PlanStatus.UNAVAILABLE
                if exc.code
                in {
                    DiagnosticCode.PLANNING_SERVER_UNAVAILABLE,
                    DiagnosticCode.PLANNING_TIMEOUT,
                }
                else PlanStatus.REJECTED
            )
            if exc.code is DiagnosticCode.ADAPTER_ERROR:
                status = PlanStatus.FAILED
            return _failure(status, exc.code, readiness, request)
        except (ArithmeticError, AttributeError, KeyError, OSError, TypeError, ValueError):
            return _failure(PlanStatus.FAILED, DiagnosticCode.ADAPTER_ERROR, readiness, request)

    def materialize(self, accepted: AcceptedTrajectory) -> ControllerTrajectorySnapshot:
        if type(accepted) is not AcceptedTrajectory:
            raise C3aError(DiagnosticCode.MATERIALIZATION_MISMATCH, "materialize requires AcceptedTrajectory")
        binding = self._accepted_bindings.get(id(accepted))
        if binding is None or binding[0] is not accepted:
            raise C3aError(
                DiagnosticCode.MATERIALIZATION_MISMATCH,
                "accepted trajectory was not planned by this C3a bridge",
            )
        readiness = binding[1]
        current_config_sha256 = self._readiness.configuration_sha256()
        if not valid_sha256(current_config_sha256) or current_config_sha256 != readiness.config_sha256:
            raise C3aError(
                DiagnosticCode.MATERIALIZATION_MISMATCH,
                "accepted trajectory was not planned under the current C3a configuration",
            )
        snapshot = accepted.snapshot
        canonical = canonical_json_bytes(
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
        if (
            canonical != accepted.canonical_bytes
            or sha256_bytes(canonical) != accepted.trajectory_sha256
            or accepted.context_sha256 != readiness.preflight_context.context_sha256
            or accepted.effective_limits_sha256 != readiness.preflight_context.effective_limits_sha256
            or snapshot.joint_names != readiness.joint_names
        ):
            raise C3aError(DiagnosticCode.MATERIALIZATION_MISMATCH, "accepted trajectory context mismatch")
        return ControllerTrajectorySnapshot(
            controller_name=readiness.controller.name,
            joint_names=tuple(snapshot.joint_names),
            points=tuple(
                ControllerTrajectoryPoint(
                    positions=tuple(point.positions),
                    velocities=tuple(point.velocities),
                    accelerations=tuple(point.accelerations),
                    effort=tuple(point.effort),
                    time_from_start_ns=point.time_from_start_ns,
                )
                for point in snapshot.points
            ),
            trajectory_sha256=accepted.trajectory_sha256,
            effective_limits_sha256=accepted.effective_limits_sha256,
            context_sha256=accepted.context_sha256,
            config_sha256=readiness.config_sha256,
        )
