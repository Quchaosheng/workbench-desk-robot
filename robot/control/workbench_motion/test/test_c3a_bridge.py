"""Public-interface tests for the ROS-free C3a deep module."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest
from workbench_motion.c3a_bridge import (
    C3aPlanOnlyBridge,
    InMemoryPlanningAdapter,
    InMemoryReadinessAdapter,
    seal_readiness,
    validate_acceptance_proof,
)
from workbench_motion.c3a_types import (
    AcceptanceProof,
    C3aError,
    ControllerIdentity,
    DiagnosticCode,
    PlanningAdapterError,
    PlanningProfile,
    PlanningResponse,
    PlanningServerUnavailable,
    PlanningTimedOut,
    PlanStatus,
    Pose,
    PosePlanGoal,
    ReadinessSnapshot,
    TransformSnapshot,
    sha256_bytes,
)
from workbench_motion.joint_limits import (
    JointLimit,
    PreflightPolicy,
    build_preflight_context,
    trajectory_canonical_bytes,
)

NAMES = ("j1", "j2")
CURRENT = (("j1", 0.0), ("j2", 0.0))
HASH = sha256_bytes(b"controlled-input")
COMPONENT_NAMES = (
    "robot_description",
    "arm.yaml",
    "workbench_arm.srdf",
    "kinematics.yaml",
    "ompl_planning.yaml",
    "moveit_joint_limits.yaml",
    "controllers.yaml",
    "trajectory_preflight.yaml",
    "joint_limits.hw_override.yaml",
)


def context():
    limits = {name: JointLimit(-2.0, 2.0, 2.0, 10.0) for name in NAMES}
    return build_preflight_context(
        policy=PreflightPolicy("test", 1e-6, 30.0, 0.2),
        expected_joint_names=NAMES,
        hard_limits=limits,
        override_limits={},
    )


def readiness(**changes):
    candidate = ReadinessSnapshot(
        model="test-arm",
        planning_group="arm",
        planning_frame="world",
        ik_tip_link="tcp",
        joint_names=NAMES,
        current_joint_positions=CURRENT,
        full_joint_positions=CURRENT,
        joint_state_timestamp_ns=9_900_000_000,
        joint_state_observed_at_ns=9_900_000_000,
        transform=TransformSnapshot(
            parent_frame="world",
            child_frame="tcp",
            translation=(0.0, 0.0, 0.0),
            rotation=(0.0, 0.0, 0.0, 1.0),
            timestamp_ns=9_950_000_000,
        ),
        transform_observed_at_ns=9_950_000_000,
        checked_at_ns=10_000_000_000,
        max_age_ns=200_000_000,
        joint_state_timestamp_clock_id="monotonic",
        transform_timestamp_clock_id="monotonic",
        joint_state_observation_clock_id="monotonic",
        transform_observation_clock_id="monotonic",
        checked_at_clock_id="monotonic",
        clock_proof_sha256=HASH,
        controller=ControllerIdentity("arm_controller", NAMES, ("position",)),
        planning_profile=PlanningProfile("ompl", "", 1, 5.0, 0.1, 0.1),
        preflight_context=context(),
        component_hashes=tuple((name, HASH) for name in COMPONENT_NAMES),
        package_versions=(("moveit", "2.10.0"), ("ros", "jazzy")),
        config_sha256="",
        readiness_sha256="",
    )
    return seal_readiness(replace(candidate, **changes))


def goal():
    return PosePlanGoal("world", Pose(0.4, 0.1, 0.8, 0.0, 0.0, 0.0, 1.0))


def trajectory(*, positions=(0.1, -0.1), names=NAMES):
    return {
        "joint_names": list(names),
        "points": [
            {
                "positions": [0.0, 0.0],
                "velocities": [],
                "accelerations": [],
                "effort": [],
                "time_from_start": 0.0,
            },
            {
                "positions": list(positions),
                "velocities": [],
                "accelerations": [],
                "effort": [],
                "time_from_start": 1.0,
            },
        ],
    }


def response(**changes):
    candidate = PlanningResponse(
        moveit_error_code=1,
        trajectory_start=CURRENT,
        trajectory=trajectory(),
    )
    return replace(candidate, **changes)


def bridge(*, plan_response=None, ready=None):
    planner = InMemoryPlanningAdapter(response() if plan_response is None else plan_response)
    readiness_adapter = InMemoryReadinessAdapter(readiness() if ready is None else ready)
    return C3aPlanOnlyBridge(planner, readiness_adapter), planner, readiness_adapter


def test_plan_accepts_closed_pose_and_exposes_only_accepted_trajectory():
    module, planner, _readiness = bridge()

    result = module.plan(goal())

    assert result.status is PlanStatus.PLANNED
    assert result.diagnostic_code is DiagnosticCode.READY
    assert result.accepted_trajectory is not None
    assert result.execution_goal_count == 0
    assert len(planner.requests) == 1
    request = planner.requests[0]
    assert request.planning_group == "arm"
    assert request.planning_frame == "world"
    assert request.ik_tip_link == "tcp"
    assert request.joint_names == NAMES
    assert request.start_positions == (0.0, 0.0)
    assert request.max_velocity_scaling_factor == 0.1
    assert request.max_acceleration_scaling_factor == 0.1


def test_materialize_uses_the_preflight_canonicalization_seam():
    module, _planner, _readiness = bridge()
    result = module.plan(goal())

    assert result.accepted_trajectory is not None
    accepted = result.accepted_trajectory
    assert accepted.canonical_bytes == trajectory_canonical_bytes(accepted.snapshot)


def test_readiness_exposes_acceptance_proof_as_a_separate_immutable_value():
    snapshot = readiness()
    proof = snapshot.acceptance_proof

    assert isinstance(proof, AcceptanceProof)
    assert proof.clock_proof_sha256 == snapshot.clock_proof_sha256
    assert proof.component_hashes == snapshot.component_hashes
    assert proof.package_versions == snapshot.package_versions
    assert validate_acceptance_proof(proof) is proof


def test_plan_preserves_the_closed_pose_and_exact_standard_tolerance():
    candidate = PosePlanGoal("world", Pose(0.4, -0.1, 0.8, 0.0, 1.0, 0.0, 0.0), "standard")
    module, planner, _readiness = bridge()

    result = module.plan(candidate)

    assert result.status is PlanStatus.PLANNED
    assert planner.requests[0].pose == candidate.pose
    assert planner.requests[0].tolerance.position_m == 0.005
    assert planner.requests[0].tolerance.orientation_rad == 0.05


def test_plan_is_deterministic_for_the_same_goal_and_readiness():
    first, _, _ = bridge()
    second, _, _ = bridge()

    a = first.plan(goal())
    b = second.plan(goal())

    assert a.planning_request_sha256 == b.planning_request_sha256
    assert a.config_sha256 == b.config_sha256
    assert a.readiness_sha256 == b.readiness_sha256
    assert a.accepted_trajectory.trajectory_sha256 == b.accepted_trajectory.trajectory_sha256


@pytest.mark.parametrize(
    "candidate",
    [
        {"frame_id": "world"},
        PosePlanGoal("unknown", Pose(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0)),
        PosePlanGoal("world", Pose(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2.0)),
        PosePlanGoal("world", Pose(0.0, 0.0, float("nan"), 0.0, 0.0, 0.0, 1.0)),
        PosePlanGoal("world", Pose(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0), "unknown"),
    ],
)
def test_raw_unknown_or_malformed_goals_fail_closed(candidate):
    module, planner, _readiness = bridge()

    result = module.plan(candidate)

    assert result.status is PlanStatus.REJECTED
    assert result.diagnostic_code is DiagnosticCode.INVALID_PLAN_REQUEST
    assert result.execution_goal_count == 0
    assert planner.requests == []


def test_goal_subclasses_cannot_expand_the_closed_input_set():
    class ExtendedGoal(PosePlanGoal):
        __slots__ = ("execute",)

    candidate = ExtendedGoal("world", goal().pose)
    object.__setattr__(candidate, "execute", True)
    module, planner, _readiness = bridge()

    result = module.plan(candidate)

    assert result.status is PlanStatus.REJECTED
    assert result.diagnostic_code is DiagnosticCode.INVALID_PLAN_REQUEST
    assert planner.requests == []


def test_mixed_readiness_clock_provenance_fails_closed():
    bad = readiness(transform_observation_clock_id="sim-time")
    module, planner, _readiness = bridge(ready=bad)

    result = module.plan(goal())

    assert result.status is PlanStatus.UNAVAILABLE
    assert result.diagnostic_code is DiagnosticCode.READINESS_UNAVAILABLE
    assert planner.requests == []


@pytest.mark.parametrize(
    "changes",
    [
        {"joint_state_timestamp_ns": 1},
        {"transform": replace(readiness().transform, timestamp_ns=1)},
        {"joint_state_timestamp_ns": 11_000_000_000},
        {"transform": replace(readiness().transform, timestamp_ns=11_000_000_000)},
    ],
)
def test_stale_or_future_source_header_timestamps_fail_closed(changes):
    candidate = readiness(**changes)
    module, planner, _readiness = bridge(ready=candidate)

    result = module.plan(goal())

    assert result.status is PlanStatus.UNAVAILABLE
    assert result.diagnostic_code is DiagnosticCode.READINESS_STALE
    assert planner.requests == []


def test_source_and_observation_freshness_at_exact_max_age_is_accepted():
    timestamp_ns = 9_800_000_000
    candidate = readiness(
        joint_state_timestamp_ns=timestamp_ns,
        joint_state_observed_at_ns=timestamp_ns,
        transform=replace(readiness().transform, timestamp_ns=timestamp_ns),
        transform_observed_at_ns=timestamp_ns,
        checked_at_ns=10_000_000_000,
        max_age_ns=200_000_000,
    )
    module, planner, _readiness = bridge(ready=candidate)

    result = module.plan(goal())

    assert result.status is PlanStatus.PLANNED
    assert len(planner.requests) == 1


def test_stale_readiness_fails_before_planning():
    stale = replace(readiness(), checked_at_ns=11_000_000_000)
    module, planner, _readiness = bridge(ready=stale)

    result = module.plan(goal())

    assert result.status is PlanStatus.UNAVAILABLE
    assert result.diagnostic_code is DiagnosticCode.READINESS_STALE
    assert planner.requests == []


def test_incomplete_controller_identity_fails_closed():
    bad = readiness(controller=ControllerIdentity("arm_controller", NAMES, ("velocity",)))
    module, planner, _readiness = bridge(ready=bad)

    result = module.plan(goal())

    assert result.status is PlanStatus.UNAVAILABLE
    assert result.diagnostic_code is DiagnosticCode.READINESS_UNAVAILABLE
    assert planner.requests == []


@pytest.mark.parametrize("bad_name", ["", 7, None])
def test_joint_names_must_be_nonempty_strings(bad_name):
    bad = readiness(joint_names=("j1", bad_name))
    module, planner, _readiness = bridge(ready=bad)

    result = module.plan(goal())

    assert result.status is PlanStatus.UNAVAILABLE
    assert result.diagnostic_code is DiagnosticCode.READINESS_UNAVAILABLE
    assert planner.requests == []


def test_readiness_hash_tampering_fails_closed():
    bad = replace(readiness(), readiness_sha256=HASH)
    module, planner, _readiness = bridge(ready=bad)

    result = module.plan(goal())

    assert result.status is PlanStatus.UNAVAILABLE
    assert result.diagnostic_code is DiagnosticCode.CONTEXT_MISMATCH
    assert planner.requests == []


@pytest.mark.parametrize(
    "error,code",
    [
        (PlanningServerUnavailable(), DiagnosticCode.PLANNING_SERVER_UNAVAILABLE),
        (PlanningTimedOut(), DiagnosticCode.PLANNING_TIMEOUT),
        (PlanningAdapterError(), DiagnosticCode.ADAPTER_ERROR),
    ],
)
def test_planning_adapter_failures_have_stable_codes_and_zero_dispatch(error, code):
    def fail(_request):
        raise error

    module, _planner, _readiness = bridge(plan_response=fail)

    result = module.plan(goal())

    assert result.diagnostic_code is code
    assert result.execution_goal_count == 0
    assert result.accepted_trajectory is None


@pytest.mark.parametrize("field", ["moveit_error_code", "multi_dof_joint_count"])
def test_boolean_planning_response_fields_are_not_coerced_to_integers(field):
    module, _planner, _readiness = bridge(plan_response=response(**{field: False if field.endswith("count") else True}))

    result = module.plan(goal())

    assert result.status is PlanStatus.FAILED
    assert result.diagnostic_code is DiagnosticCode.ADAPTER_ERROR


@pytest.mark.parametrize(
    "trajectory_start",
    [
        (("j1", 0.0), ("j2", 0.0), ("unexpected", 0.0)),
        (("j2", 0.0), ("j1", 0.0)),
    ],
)
def test_trajectory_start_rejects_unexpected_or_reordered_joints_even_when_values_match(trajectory_start):
    module, _planner, _readiness = bridge(plan_response=response(trajectory_start=trajectory_start))

    result = module.plan(goal())

    assert result.status is PlanStatus.REJECTED
    assert result.diagnostic_code is DiagnosticCode.CONTEXT_MISMATCH


def test_planning_adapter_error_is_failed_not_rejected():
    module, _planner, _readiness = bridge(plan_response=lambda _request: (_ for _ in ()).throw(PlanningAdapterError()))

    result = module.plan(goal())

    assert result.status is PlanStatus.FAILED
    assert result.diagnostic_code is DiagnosticCode.ADAPTER_ERROR


def test_moveit_rejection_preserves_source_code():
    module, _planner, _readiness = bridge(plan_response=response(moveit_error_code=-31))

    result = module.plan(goal())

    assert result.status is PlanStatus.REJECTED
    assert result.diagnostic_code is DiagnosticCode.PLANNING_REJECTED
    assert result.moveit_error_code == -31


@pytest.mark.parametrize(
    "plan_response,code,source_code",
    [
        (response(trajectory=None), DiagnosticCode.EMPTY_PLAN, None),
        (response(multi_dof_joint_count=1), DiagnosticCode.TRAJECTORY_REJECTED, None),
        (
            response(trajectory=trajectory(positions=(3.0, 0.0))),
            DiagnosticCode.TRAJECTORY_REJECTED,
            "position",
        ),
        (
            response(trajectory_start=(("j1", 0.01), ("j2", 0.0))),
            DiagnosticCode.CONTEXT_MISMATCH,
            None,
        ),
    ],
)
def test_candidate_and_start_state_failures_never_expose_raw_trajectory(plan_response, code, source_code):
    module, _planner, _readiness = bridge(plan_response=plan_response)

    result = module.plan(goal())

    assert result.status is PlanStatus.REJECTED
    assert result.diagnostic_code is code
    assert result.preflight_reason_code == source_code
    assert result.accepted_trajectory is None
    assert not hasattr(result, "trajectory")


def test_plan_accepts_trajectory_at_exact_preflight_start_delta_boundary():
    boundary_trajectory = {
        "joint_names": list(NAMES),
        "points": [
            {
                "positions": [0.2, 0.0],
                "velocities": [],
                "accelerations": [],
                "effort": [],
                "time_from_start": 0.2,
            },
            {
                "positions": [0.3, -0.1],
                "velocities": [],
                "accelerations": [],
                "effort": [],
                "time_from_start": 1.0,
            },
        ],
    }
    module, _planner, _readiness = bridge(plan_response=response(trajectory=boundary_trajectory))

    result = module.plan(goal())

    assert result.status is PlanStatus.PLANNED
    assert result.accepted_trajectory is not None


def test_materialize_returns_deeply_immutable_integer_nanosecond_snapshot():
    module, _planner, _readiness = bridge()
    accepted = module.plan(goal()).accepted_trajectory

    snapshot = module.materialize(accepted)

    assert snapshot.controller_name == "arm_controller"
    assert snapshot.joint_names == NAMES
    assert snapshot.points[-1].time_from_start_ns == 1_000_000_000
    assert not hasattr(snapshot, "send")
    with pytest.raises(FrozenInstanceError):
        snapshot.controller_name = "other"


def test_materialize_rejects_wrong_type_and_unbound_accepted_trajectory():
    module, _planner, _readiness = bridge()
    other, _other_planner, _other_readiness = bridge()
    accepted_elsewhere = other.plan(goal()).accepted_trajectory

    with pytest.raises(C3aError, match="requires AcceptedTrajectory") as wrong_type:
        module.materialize({})
    assert wrong_type.value.code is DiagnosticCode.MATERIALIZATION_MISMATCH

    with pytest.raises(C3aError, match="not planned by") as unbound:
        module.materialize(accepted_elsewhere)
    assert unbound.value.code is DiagnosticCode.MATERIALIZATION_MISMATCH


def test_materialize_rejects_current_configuration_change():
    initial = readiness()
    current = [initial]
    module = C3aPlanOnlyBridge(
        InMemoryPlanningAdapter(response()),
        InMemoryReadinessAdapter(lambda: current[0]),
    )
    accepted = module.plan(goal()).accepted_trajectory
    current[0] = readiness(controller=ControllerIdentity("changed", NAMES, ("position",)))

    with pytest.raises(C3aError, match="current C3a configuration") as mismatch:
        module.materialize(accepted)
    assert mismatch.value.code is DiagnosticCode.MATERIALIZATION_MISMATCH


def test_materialize_reuses_planning_readiness_and_only_rechecks_configuration():
    class OneShotReadiness:
        def __init__(self):
            self.value = readiness()
            self.snapshot_calls = 0
            self.configuration_calls = 0

        def snapshot(self):
            self.snapshot_calls += 1
            if self.snapshot_calls != 1:
                raise AssertionError("fresh readiness must be captured once per plan")
            return self.value

        def configuration_sha256(self):
            self.configuration_calls += 1
            return self.value.config_sha256

    one_shot = OneShotReadiness()
    module = C3aPlanOnlyBridge(InMemoryPlanningAdapter(response()), one_shot)

    accepted = module.plan(goal()).accepted_trajectory
    snapshot = module.materialize(accepted)

    assert snapshot.config_sha256 == one_shot.value.config_sha256
    assert one_shot.snapshot_calls == 1
    assert one_shot.configuration_calls == 1


def test_repeated_materialization_is_stable_and_does_not_mutate_accepted_snapshot():
    module, _planner, _readiness = bridge()
    accepted = module.plan(goal()).accepted_trajectory

    before = accepted.canonical_bytes
    first = module.materialize(accepted)
    second = module.materialize(accepted)

    assert first == second
    assert accepted.canonical_bytes == before
