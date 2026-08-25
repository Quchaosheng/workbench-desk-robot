"""Boundary and determinism tests for Issue #57 trajectory preflight."""

from __future__ import annotations

import copy
import json
import math
from dataclasses import FrozenInstanceError, asdict, replace
from itertools import permutations
from types import SimpleNamespace

import pytest
import workbench_motion.joint_limits as joint_limits_module
from workbench_motion.arm_config import load_arm_config
from workbench_motion.joint_limits import (
    AcceptedTrajectory,
    ConfigurationCode,
    JointLimit,
    PreflightConfigurationError,
    PreflightPolicy,
    ReasonCode,
    Violation,
    build_preflight_context,
    check_trajectory,
    load_preflight_policy,
    preflight_trajectory,
)

NAMES = ("j1", "j2")
LIMITS = {
    "j1": JointLimit(-1.0, 1.0, 100.0, 20.0),
    "j2": JointLimit(-2.0, 2.0, 100.0, 30.0),
}
POLICY = PreflightPolicy("test-1", 1e-6, 30.0, 0.05)
CURRENT = {"j1": 0.0, "j2": 0.0}


def context(*, names=NAMES, limits=None, policy=POLICY):
    hard = dict(LIMITS if limits is None else limits)
    return build_preflight_context(
        policy=policy,
        expected_joint_names=names,
        hard_limits=hard,
        override_limits={},
    )


def point(t, positions=(0.0, 0.0), velocities=(), accelerations=(), effort=()):
    return {
        "positions": list(positions),
        "velocities": list(velocities),
        "accelerations": list(accelerations),
        "effort": list(effort),
        "time_from_start": t,
    }


def trajectory(*points, names=NAMES):
    return {"joint_names": list(names), "points": list(points)}


def run(candidate, *, current=CURRENT, ctx=None):
    return preflight_trajectory(candidate, current, context=context() if ctx is None else ctx)


def accepted(candidate, *, current=CURRENT, ctx=None):
    result = run(candidate, current=current, ctx=ctx)
    assert isinstance(result, AcceptedTrajectory), result
    return result


def rejected(candidate, code, *, current=CURRENT, ctx=None):
    result = run(candidate, current=current, ctx=ctx)
    assert isinstance(result, Violation)
    assert result.kind == code
    return result


def test_reason_code_values_are_frozen_and_append_only():
    assert {code.value for code in ReasonCode} == {
        "joint_names",
        "current_state",
        "points",
        "array_length",
        "non_finite",
        "time",
        "current_position",
        "position",
        "velocity",
        "effort",
        "initial_position",
        "segment_velocity",
        "joint_order_mismatch",
        "timestamp_malformed",
        "duration_exceeded",
        "start_state_discontinuity",
    }


def test_joint_identity_and_every_non_identity_arm_permutation_are_rejected():
    arm_names = tuple(load_arm_config().joints)
    arm_limits = {name: JointLimit(-1.0, 1.0, 10.0, 10.0) for name in arm_names}
    ctx = context(names=arm_names, limits=arm_limits)
    current = dict.fromkeys(arm_names, 0.0)
    base_point = point(0.0, positions=(0.0,) * len(arm_names))
    for order in permutations(arm_names):
        result = preflight_trajectory(trajectory(base_point, names=order), current, context=ctx)
        if order == arm_names:
            assert isinstance(result, AcceptedTrajectory)
        else:
            assert isinstance(result, Violation)
            assert result.kind == ReasonCode.JOINT_ORDER_MISMATCH


@pytest.mark.parametrize(
    "names,code",
    [
        ((), ReasonCode.JOINT_NAMES),
        (("j1", "j1"), ReasonCode.JOINT_NAMES),
        (("j1", "other"), ReasonCode.JOINT_NAMES),
        (("j2", "j1"), ReasonCode.JOINT_ORDER_MISMATCH),
    ],
)
def test_joint_name_failures(names, code):
    rejected(trajectory(point(0.0), names=names), code)


def test_every_configured_joint_position_velocity_and_effort_boundary():
    arm_names = tuple(load_arm_config().joints)
    limits = {name: JointLimit(-1.0, 1.0, 10.0, 20.0) for name in arm_names}
    ctx = context(names=arm_names, limits=limits)
    current = dict.fromkeys(arm_names, 0.0)
    zeros = [0.0] * len(arm_names)
    epsilon = POLICY.limit_epsilon

    for offset, joint in enumerate(arm_names):
        for value in (-1.0 + epsilon, 1.0 - epsilon):
            positions = zeros.copy()
            positions[offset] = value
            candidate = trajectory(point(0.0, positions=zeros), point(1.0, positions=positions), names=arm_names)
            accepted(candidate, current=current, ctx=ctx)
        for value in (-1.0 + epsilon - 1e-9, 1.0 - epsilon + 1e-9):
            positions = zeros.copy()
            positions[offset] = value
            violation = rejected(
                trajectory(point(0.0, positions=zeros), point(1.0, positions=positions), names=arm_names),
                ReasonCode.POSITION,
                current=current,
                ctx=ctx,
            )
            assert violation.joint == joint

        for sign in (-1.0, 1.0):
            for magnitude in (10.0 - epsilon, 10.0 - epsilon - 1e-9):
                velocities = zeros.copy()
                velocities[offset] = sign * magnitude
                candidate = trajectory(point(0.0, positions=zeros, velocities=velocities), names=arm_names)
                accepted(candidate, current=current, ctx=ctx)
            velocities = zeros.copy()
            velocities[offset] = sign * (10.0 - epsilon + 1e-9)
            assert (
                rejected(
                    trajectory(point(0.0, positions=zeros, velocities=velocities), names=arm_names),
                    ReasonCode.VELOCITY,
                    current=current,
                    ctx=ctx,
                ).joint
                == joint
            )

        efforts = zeros.copy()
        efforts[offset] = -(20.0 - epsilon)
        accepted(trajectory(point(0.0, positions=zeros, effort=efforts), names=arm_names), current=current, ctx=ctx)
        efforts[offset] -= 1e-9
        assert (
            rejected(
                trajectory(point(0.0, positions=zeros, effort=efforts), names=arm_names),
                ReasonCode.EFFORT,
                current=current,
                ctx=ctx,
            ).joint
            == joint
        )


@pytest.mark.parametrize(
    "timestamp",
    [
        True,
        "1.0",
        1e-10,
        {},
        {"sec": 0},
        {"nanosec": 0},
        {"sec": True, "nanosec": 0},
        {"sec": 0, "nanosec": False},
        {"sec": 0.0, "nanosec": 0},
        {"sec": -(2**31) - 1, "nanosec": 0},
        {"sec": 2**31, "nanosec": 0},
        {"sec": 0, "nanosec": -1},
        {"sec": 0, "nanosec": 1_000_000_000},
        SimpleNamespace(sec=0),
    ],
)
def test_malformed_timestamp_shapes_fail(timestamp):
    rejected(trajectory(point(timestamp)), ReasonCode.TIMESTAMP_MALFORMED)


@pytest.mark.parametrize("timestamp", [math.nan, math.inf, -math.inf])
def test_non_finite_scalar_timestamps_keep_legacy_code(timestamp):
    rejected(trajectory(point(timestamp)), ReasonCode.NON_FINITE)


def test_integer_nanosecond_time_edges_and_negative_zero_normalization():
    assert accepted(trajectory(point(-0.0))).snapshot.points[0].time_from_start_ns == 0
    assert accepted(trajectory(point(0.000000001))).snapshot.points[0].time_from_start_ns == 1
    rejected(
        trajectory(point({"sec": 2**31 - 1, "nanosec": 0})),
        ReasonCode.DURATION_EXCEEDED,
    )
    rejected(trajectory(point({"sec": -1, "nanosec": 999_999_999})), ReasonCode.TIME)


@pytest.mark.parametrize("timestamp", [2**31, 2**31 + 0.5, 10**400])
def test_scalar_seconds_above_structured_int32_range_parse_before_duration_check(timestamp):
    rejected(trajectory(point(timestamp)), ReasonCode.DURATION_EXCEEDED)


@pytest.mark.parametrize("timestamp", [-(2**31) - 1, -(10**400)])
def test_negative_scalar_seconds_below_structured_int32_range_parse_before_time_check(timestamp):
    rejected(trajectory(point(timestamp)), ReasonCode.TIME)


@pytest.mark.parametrize(
    "duration",
    [
        pytest.param(lambda sec, nanosec: {"sec": sec, "nanosec": nanosec}, id="mapping"),
        pytest.param(lambda sec, nanosec: SimpleNamespace(sec=sec, nanosec=nanosec), id="object"),
    ],
)
def test_structured_timestamp_int32_sec_and_nanosec_boundaries(duration):
    rejected(trajectory(point(duration(-(2**31), 0))), ReasonCode.TIME)
    rejected(trajectory(point(duration(-(2**31), 999_999_999))), ReasonCode.TIME)
    rejected(trajectory(point(duration(2**31 - 1, 0))), ReasonCode.DURATION_EXCEEDED)
    rejected(trajectory(point(duration(2**31 - 1, 999_999_999))), ReasonCode.DURATION_EXCEEDED)
    accepted(trajectory(point(duration(0, 0))))
    accepted(trajectory(point(duration(0, 999_999_999))))
    rejected(trajectory(point(duration(0, -1))), ReasonCode.TIMESTAMP_MALFORMED)
    rejected(trajectory(point(duration(0, 1_000_000_000))), ReasonCode.TIMESTAMP_MALFORMED)


def test_time_must_be_strictly_increasing():
    rejected(trajectory(point(0.0), point(0.0)), ReasonCode.TIME)
    rejected(trajectory(point(1.0), point(0.5)), ReasonCode.TIME)


def test_duration_boundary_is_inclusive_and_one_nanosecond_over_fails():
    accepted(trajectory(point(30.0)))
    violation = rejected(trajectory(point(30.000000001)), ReasonCode.DURATION_EXCEEDED)
    assert (violation.value, violation.bound) == (30.000000001, 30.0)


def test_non_increasing_time_precedes_duration_and_reports_later_point():
    violation = rejected(trajectory(point(31.0), point(30.0)), ReasonCode.TIME)
    assert violation.point_index == 1


def test_total_duration_uses_only_the_final_point():
    violation = rejected(trajectory(point(31.0), point(32.0)), ReasonCode.DURATION_EXCEEDED)
    assert (violation.point_index, violation.value) == (1, 32.0)


def test_start_state_delta_and_t0_anchor_boundaries():
    accepted(trajectory(point(1.0, positions=(0.05, -0.05))))
    violation = rejected(trajectory(point(1.0, positions=(0.050000001, 0.0))), ReasonCode.START_STATE_DISCONTINUITY)
    assert violation.joint == "j1"
    accepted(trajectory(point(0.0, positions=(1e-6, -1e-6))))
    rejected(trajectory(point(0.0, positions=(1.0000001e-6, 0.0))), ReasonCode.INITIAL_POSITION)


def test_mean_segment_velocity_is_checked_after_start_delta():
    slow_limits = {name: replace(limit, max_velocity=1.0) for name, limit in LIMITS.items()}
    ctx = context(limits=slow_limits)
    violation = rejected(trajectory(point(0.01, positions=(0.02, 0.0))), ReasonCode.SEGMENT_VELOCITY, ctx=ctx)
    assert violation.joint == "j1"


def test_array_lengths_are_checked_globally_before_numeric_values():
    candidate = trajectory(
        point(0.0, positions=(math.nan, 0.0)),
        {"positions": [0.0], "time_from_start": 1.0},
    )
    violation = rejected(candidate, ReasonCode.ARRAY_LENGTH)
    assert violation.point_index == 1


def test_all_point_numeric_finiteness_precedes_all_timestamp_shape_checks():
    candidate = trajectory(
        point(True),
        point(1.0, positions=(math.nan, 0.0)),
    )
    violation = rejected(candidate, ReasonCode.NON_FINITE)
    assert violation.point_index == 1


def test_all_timestamp_scalar_finiteness_precedes_timestamp_shape_checks():
    candidate = trajectory(
        point(True),
        point(math.nan),
    )
    violation = rejected(candidate, ReasonCode.NON_FINITE)
    assert violation.point_index == 1


def test_all_current_state_finiteness_precedes_current_position_limits():
    violation = rejected(
        trajectory(point(0.0)),
        ReasonCode.NON_FINITE,
        current={"j1": 2.0, "j2": math.nan},
    )
    assert violation.joint == "j2"


@pytest.mark.parametrize("field", ["positions", "velocities", "accelerations", "effort"])
def test_bool_and_non_finite_arrays_fail_without_mutation(field):
    candidate = point(0.0)
    candidate[field] = [True, 0.0]
    traj = trajectory(candidate)
    before = copy.deepcopy(traj)
    rejected(traj, ReasonCode.NON_FINITE)
    assert traj == before


def test_mapping_and_ros_like_inputs_have_identical_canonical_bytes():
    mapping = trajectory(
        point(
            {"sec": 1, "nanosec": 250_000_000},
            positions=(0.01, -0.02),
            velocities=(0.1, -0.1),
            accelerations=(0.2, -0.2),
            effort=(1.0, -1.0),
        )
    )
    ros_like = SimpleNamespace(
        joint_names=list(NAMES),
        points=[
            SimpleNamespace(
                positions=(0.01, -0.02),
                velocities=(0.1, -0.1),
                accelerations=(0.2, -0.2),
                effort=(1.0, -1.0),
                time_from_start=SimpleNamespace(sec=1, nanosec=250_000_000),
            )
        ],
    )
    left = accepted(mapping)
    right = accepted(ros_like)
    scalar = copy.deepcopy(mapping)
    scalar["points"][0]["time_from_start"] = 1.25
    scalar_result = accepted(scalar)
    assert left.canonical_bytes == right.canonical_bytes
    assert left.canonical_bytes == scalar_result.canonical_bytes
    assert left.trajectory_sha256 == right.trajectory_sha256 == scalar_result.trajectory_sha256
    payload = json.loads(left.canonical_bytes)
    assert payload["points"][0]["time_from_start_ns"] == 1_250_000_000
    assert payload["points"][0]["positions"][0] == (0.01).hex()


def test_absent_optional_arrays_normalize_to_empty_lists():
    result = accepted({"joint_names": list(NAMES), "points": [{"positions": [0.0, 0.0], "time_from_start": 0}]})
    payload = json.loads(result.canonical_bytes)
    assert payload["points"][0]["velocities"] == []
    assert payload["points"][0]["accelerations"] == []
    assert payload["points"][0]["effort"] == []


def test_accepted_snapshot_is_isolated_and_deeply_immutable():
    candidate = trajectory(point(0.0), point(1.0, positions=(0.01, 0.02)))
    result = accepted(candidate)
    original_bytes = result.canonical_bytes
    candidate["joint_names"][0] = "mutated"
    candidate["points"][1]["positions"][0] = 0.5
    assert result.snapshot.joint_names == NAMES
    assert result.snapshot.points[1].positions == (0.01, 0.02)
    assert result.canonical_bytes == original_bytes
    with pytest.raises(FrozenInstanceError):
        result.snapshot.points[0].time_from_start_ns = 5
    with pytest.raises(TypeError):
        result.snapshot.points[0].positions[0] = 1.0
    with pytest.raises(TypeError, match="only be created"):
        AcceptedTrajectory()


def test_canonical_bytes_repeat_and_each_content_mutation_changes_hash():
    base = trajectory(point(0.0), point(1.0, positions=(0.01, 0.02)))
    baseline = accepted(base)
    assert accepted(copy.deepcopy(base)).canonical_bytes == baseline.canonical_bytes
    mutations = []
    changed_position = copy.deepcopy(base)
    changed_position["points"][1]["positions"][0] = 0.011
    mutations.append(changed_position)
    changed_time = copy.deepcopy(base)
    changed_time["points"][1]["time_from_start"] = 1.1
    mutations.append(changed_time)
    for field in ("velocities", "accelerations", "effort"):
        changed_array = copy.deepcopy(base)
        changed_array["points"][1][field] = [0.01, 0.0]
        mutations.append(changed_array)
    added_point = copy.deepcopy(base)
    added_point["points"].append(point(2.0, positions=(0.02, 0.03)))
    mutations.append(added_point)
    assert all(accepted(candidate).trajectory_sha256 != baseline.trajectory_sha256 for candidate in mutations)


def test_mutating_each_configured_joint_changes_trajectory_hash():
    arm_names = tuple(load_arm_config().joints)
    limits = {name: JointLimit(-1.0, 1.0, 10.0, 10.0) for name in arm_names}
    ctx = context(names=arm_names, limits=limits)
    current = dict.fromkeys(arm_names, 0.0)
    zeros = [0.0] * len(arm_names)
    base = trajectory(point(0.0, positions=zeros), point(1.0, positions=zeros), names=arm_names)
    baseline = accepted(base, current=current, ctx=ctx)
    for offset, _joint in enumerate(arm_names):
        candidate = copy.deepcopy(base)
        candidate["points"][1]["positions"][offset] = 0.001
        result = accepted(candidate, current=current, ctx=ctx)
        assert result.trajectory_sha256 != baseline.trajectory_sha256


def test_trajectory_hash_excludes_policy_and_limit_context():
    candidate = trajectory(point(0.0), point(1.0, positions=(0.01, 0.02)))
    baseline = accepted(candidate)
    policy_context = context(policy=replace(POLICY, version="test-2", max_duration_s=31.0))
    policy_result = accepted(candidate, ctx=policy_context)
    changed_limits = dict(LIMITS)
    changed_limits["j1"] = replace(changed_limits["j1"], max_effort=19.0)
    limits_result = accepted(candidate, ctx=context(limits=changed_limits))
    assert baseline.trajectory_sha256 == policy_result.trajectory_sha256 == limits_result.trajectory_sha256
    assert baseline.context_sha256 != policy_result.context_sha256
    assert baseline.effective_limits_sha256 == policy_result.effective_limits_sha256
    assert baseline.effective_limits_sha256 != limits_result.effective_limits_sha256


def test_expected_joint_tuple_order_changes_context_evidence():
    baseline = context()
    reordered = context(names=tuple(reversed(NAMES)))
    assert reordered.expected_joint_names != baseline.expected_joint_names
    assert reordered.effective_limits_sha256 != baseline.effective_limits_sha256
    assert reordered.context_sha256 != baseline.context_sha256


def test_violation_asdict_and_json_keep_exact_legacy_six_fields():
    violation = rejected(trajectory(point(1.0, positions=(1.0, 0.0))), ReasonCode.POSITION)
    payload = asdict(violation)
    assert tuple(payload) == ("kind", "message", "joint", "value", "bound", "point_index")
    assert json.loads(json.dumps(payload))["kind"] == "position"
    assert violation.code is ReasonCode.POSITION


def test_legacy_wrapper_uses_supplied_mapping_order_and_return_contract():
    reverse_limits = {"j2": LIMITS["j2"], "j1": LIMITS["j1"]}
    reverse = trajectory(point(0.0), names=("j2", "j1"))
    assert check_trajectory(reverse, CURRENT, reverse_limits) is None
    violation = check_trajectory(trajectory(point(0.0)), CURRENT, reverse_limits)
    assert isinstance(violation, Violation)
    assert violation.kind == ReasonCode.JOINT_ORDER_MISMATCH


def test_shipped_policy_values_are_frozen():
    assert load_preflight_policy() == PreflightPolicy("1", 0.000001, 30.0, 0.05)


@pytest.mark.parametrize(
    "policy",
    [
        {"version": "1", "limit_epsilon": 1e-6, "max_duration_s": 30.0},
        {
            "version": "1",
            "limit_epsilon": 1e-6,
            "max_duration_s": 30.0,
            "max_start_state_delta_rad": 0.05,
            "unknown": 1,
        },
        {"version": "1", "limit_epsilon": True, "max_duration_s": 30.0, "max_start_state_delta_rad": 0.05},
        {"version": "1", "limit_epsilon": -1.0, "max_duration_s": 30.0, "max_start_state_delta_rad": 0.05},
        {"version": "1", "limit_epsilon": 1e-6, "max_duration_s": math.inf, "max_start_state_delta_rad": 0.05},
        {"version": "1", "limit_epsilon": 1e-6, "max_duration_s": 1e-10, "max_start_state_delta_rad": 0.05},
        {"version": "1", "limit_epsilon": 1e-6, "max_duration_s": 30.0, "max_start_state_delta_rad": 0.0},
    ],
)
def test_invalid_explicit_policy_fails_as_configuration(policy):
    with pytest.raises(PreflightConfigurationError) as caught:
        context(policy=policy)
    assert caught.value.code == ConfigurationCode.INVALID_POLICY


def test_extreme_integer_policy_fails_with_stable_configuration_code():
    extreme = replace(POLICY, max_duration_s=10**400)
    with pytest.raises(PreflightConfigurationError) as caught:
        context(policy=extreme)
    assert caught.value.code == ConfigurationCode.INVALID_POLICY


def test_policy_file_missing_unknown_and_bool_fields_fail_closed(tmp_path):
    malformed = tmp_path / "policy.yaml"
    malformed.write_text(
        "trajectory_preflight:\n"
        "  version: '1'\n"
        "  limit_epsilon: true\n"
        "  max_duration_s: 30.0\n"
        "  max_start_state_delta_rad: 0.05\n",
        encoding="utf-8",
    )
    with pytest.raises(PreflightConfigurationError) as caught:
        load_preflight_policy(malformed)
    assert caught.value.code == ConfigurationCode.INVALID_POLICY


@pytest.mark.parametrize(
    "names,limits,policy",
    [
        (("j1",), LIMITS, POLICY),
        (NAMES, {"j1": LIMITS["j1"]}, POLICY),
        (NAMES, {"j1": JointLimit(math.nan, 1.0, 1.0, 1.0), "j2": LIMITS["j2"]}, POLICY),
        (NAMES, {"j1": JointLimit(1.0, -1.0, 1.0, 1.0), "j2": LIMITS["j2"]}, POLICY),
        (NAMES, LIMITS, replace(POLICY, limit_epsilon=2.0)),
    ],
)
def test_invalid_limits_fail_as_configuration(names, limits, policy):
    with pytest.raises(PreflightConfigurationError) as caught:
        context(names=names, limits=limits, policy=policy)
    assert caught.value.code == ConfigurationCode.INVALID_LIMITS


def test_extreme_integer_hard_limit_fails_with_stable_configuration_code():
    hard = dict(LIMITS)
    hard["j1"] = replace(hard["j1"], max_effort=10**400)
    with pytest.raises(PreflightConfigurationError) as caught:
        context(limits=hard)
    assert caught.value.code == ConfigurationCode.INVALID_LIMITS


@pytest.mark.parametrize("field", ["min_position", "max_position", "max_velocity", "max_effort"])
def test_extreme_integer_hard_limit_cannot_be_masked_by_normal_override(field):
    hard = dict(LIMITS)
    hard["j1"] = replace(hard["j1"], **{field: 10**400})
    with pytest.raises(PreflightConfigurationError) as caught:
        build_preflight_context(
            policy=POLICY,
            expected_joint_names=NAMES,
            hard_limits=hard,
            override_limits={"j1": LIMITS["j1"]},
        )
    assert caught.value.code == ConfigurationCode.INVALID_LIMITS


@pytest.mark.parametrize(
    "override",
    [
        {"j1": JointLimit(-2.0, 2.0, 200.0, 40.0)},
        {"j1": JointLimit(-2.0, 1.0, 100.0, 20.0)},
        {"j1": JointLimit(-1.0, 2.0, 100.0, 20.0)},
        {"j1": JointLimit(-1.0, 1.0, 101.0, 20.0)},
        {"j1": JointLimit(-1.0, 1.0, 100.0, 21.0)},
    ],
)
def test_explicit_override_cannot_be_looser_than_hard_limits(override):
    with pytest.raises(PreflightConfigurationError) as caught:
        build_preflight_context(
            policy=POLICY,
            expected_joint_names=NAMES,
            hard_limits=LIMITS,
            override_limits=override,
        )
    assert caught.value.code == ConfigurationCode.INVALID_LIMITS
    assert "looser" in str(caught.value)


def test_extreme_integer_override_fails_with_stable_configuration_code():
    with pytest.raises(PreflightConfigurationError) as caught:
        build_preflight_context(
            policy=POLICY,
            expected_joint_names=NAMES,
            hard_limits=LIMITS,
            override_limits={"j1": replace(LIMITS["j1"], max_effort=10**400)},
        )
    assert caught.value.code == ConfigurationCode.INVALID_LIMITS


def test_context_content_hash_mismatch_fails_closed():
    ctx = replace(context(), context_sha256="sha256:" + "0" * 64)
    with pytest.raises(PreflightConfigurationError) as caught:
        preflight_trajectory(trajectory(point(0.0)), CURRENT, context=ctx)
    assert caught.value.code == ConfigurationCode.INVALID_LIMITS


def test_explicit_integer_limits_are_normalized_for_context_hashing():
    integer_limits = {
        "j1": JointLimit(-1, 1, 100, 20),
        "j2": JointLimit(-2, 2, 100, 30),
    }
    assert isinstance(accepted(trajectory(point(0)), ctx=context(limits=integer_limits)), AcceptedTrajectory)


def test_explicit_sources_replace_file_sources_and_limit_order_is_canonical(monkeypatch):
    baseline = context()

    def unexpected_file_load(*args, **kwargs):
        raise AssertionError("an explicit source must not consult controlled files")

    monkeypatch.setattr(joint_limits_module, "load_arm_config", unexpected_file_load)
    monkeypatch.setattr(joint_limits_module, "load_preflight_policy", unexpected_file_load)
    monkeypatch.setattr(joint_limits_module, "load_hard_limits", unexpected_file_load)
    monkeypatch.setattr(joint_limits_module, "load_hw_override", unexpected_file_load)
    reverse_limits = {"j2": LIMITS["j2"], "j1": LIMITS["j1"]}
    explicit = build_preflight_context(
        policy=POLICY,
        expected_joint_names=NAMES,
        hard_limits=reverse_limits,
        override_limits={},
    )
    assert explicit.effective_limits == tuple(LIMITS.items())
    assert explicit.effective_limits_sha256 == baseline.effective_limits_sha256
    assert explicit.context_sha256 == baseline.context_sha256


def test_forged_context_with_invalid_policy_fails_as_policy_configuration():
    forged = replace(context(), policy=replace(POLICY, max_duration_s=math.nan))
    with pytest.raises(PreflightConfigurationError) as caught:
        preflight_trajectory(trajectory(point(0.0)), CURRENT, context=forged)
    assert caught.value.code == ConfigurationCode.INVALID_POLICY


def test_fixed_first_error_order_is_deterministic():
    candidate = trajectory({"positions": [math.nan, 0.0], "time_from_start": True}, names=("j2", "j1"))
    assert rejected(candidate, ReasonCode.JOINT_ORDER_MISMATCH).point_index is None
    candidate = trajectory({"positions": [math.nan, 0.0], "time_from_start": True})
    rejected(candidate, ReasonCode.NON_FINITE)
    first = rejected(trajectory(point(31.0, positions=(2.0, 0.0))), ReasonCode.DURATION_EXCEEDED)
    second = rejected(trajectory(point(31.0, positions=(2.0, 0.0))), ReasonCode.DURATION_EXCEEDED)
    assert asdict(first) == asdict(second)
