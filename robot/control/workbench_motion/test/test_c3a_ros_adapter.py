"""Message-shape and transport tests for the C3a MoveGroup-only adapter."""

from __future__ import annotations

import ast
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest
import workbench_motion.c3a_ros_adapter as ros_adapter_module
from workbench_motion.c3a_ros_adapter import (
    MoveGroupPlanningAdapter,
    RclpyMoveGroupTransport,
    RosReadinessAdapter,
    _bind_sample_clock_proof,
    _controller_identity,
    _MessageTypes,
    _planning_profile,
    _prove_source_clock_domain,
    _read_provenance_payload,
    _stamp_ns,
    _wait_for_provenance_payload,
    build_move_group_goal,
)
from workbench_motion.c3a_types import (
    ControllerIdentity,
    DiagnosticCode,
    GoalTolerance,
    PlanningAdapterError,
    PlanningProfile,
    PlanningRequest,
    PlanningServerUnavailable,
    PlanningTimedOut,
    Pose,
    ReadinessError,
    canonical_json_bytes,
    sha256_bytes,
)


def namespace(**values):
    return SimpleNamespace(**values)


def _graph_clock_proof_result():
    proof = {
        "schema_version": "c3a-clock-proof-1",
        "domain_id": "ros:1:system",
        "publishers_by_topic": {
            "/joint_states": ["/joint_state_publisher"],
            "/tf": ["/robot_state_publisher"],
            "/tf_static": ["/robot_state_publisher"],
        },
        "publisher_use_sim_time": {
            "/joint_state_publisher": False,
            "/robot_state_publisher": False,
        },
        "publisher_gids_by_topic": {
            "/joint_states": [b"joint".hex()],
            "/tf": [b"tf".hex()],
            "/tf_static": [],
        },
    }
    return (
        "ros:1:system",
        sha256_bytes(canonical_json_bytes(proof)),
        {"/joint_states": frozenset({b"joint"}), "/tf": frozenset({b"tf"}), "/tf_static": frozenset()},
        proof,
    )


class GoalMessage:
    def __init__(self):
        self.request = namespace(
            group_name="",
            pipeline_id="",
            planner_id="",
            num_planning_attempts=0,
            allowed_planning_time=0.0,
            max_velocity_scaling_factor=0.0,
            max_acceleration_scaling_factor=0.0,
            start_state=namespace(
                joint_state=namespace(name=[], position=[]),
                is_diff=True,
            ),
            goal_constraints=[],
        )
        self.planning_options = namespace(
            plan_only=False,
            look_around=True,
            replan=True,
            replan_attempts=99,
            replan_delay=99.0,
        )


class PoseMessage:
    def __init__(self):
        self.position = namespace(x=0.0, y=0.0, z=0.0)
        self.orientation = namespace(x=0.0, y=0.0, z=0.0, w=1.0)


class SolidPrimitiveMessage:
    def __init__(self):
        self.type = 0
        self.dimensions = []


class PositionConstraintMessage:
    def __init__(self):
        self.header = namespace(frame_id="")
        self.link_name = ""
        self.constraint_region = namespace(primitives=[], primitive_poses=[])
        self.weight = 0.0


class OrientationConstraintMessage:
    def __init__(self):
        self.header = namespace(frame_id="")
        self.link_name = ""
        self.orientation = None
        self.absolute_x_axis_tolerance = 0.0
        self.absolute_y_axis_tolerance = 0.0
        self.absolute_z_axis_tolerance = 0.0
        self.weight = 0.0


class ConstraintsMessage:
    def __init__(self):
        self.position_constraints = []
        self.orientation_constraints = []


MESSAGE_TYPES = _MessageTypes(
    goal=GoalMessage,
    constraints=ConstraintsMessage,
    position_constraint=PositionConstraintMessage,
    orientation_constraint=OrientationConstraintMessage,
    solid_primitive=SolidPrimitiveMessage,
    pose=PoseMessage,
)
_POINT = object()


def request():
    return PlanningRequest(
        planning_group="arm",
        planning_frame="world",
        ik_tip_link="tcp",
        joint_names=("j1", "j2"),
        start_positions=(0.1, -0.2),
        full_start_positions=(("j1", 0.1), ("j2", -0.2), ("gripper", 0.0)),
        pose=Pose(0.4, 0.1, 0.8, 0.0, 0.0, 0.0, 1.0),
        tolerance=GoalTolerance(0.005, 0.05),
        pipeline_id="ompl",
        planner_id="",
        num_planning_attempts=1,
        allowed_planning_time_s=5.0,
        max_velocity_scaling_factor=1.0,
        max_acceleration_scaling_factor=1.0,
        planning_request_sha256="sha256:" + "0" * 64,
    )


def move_group_result(
    *,
    points=(_POINT,),
    multi_names=(),
    multi_points=(),
    start_names=("j1", "j2", "gripper"),
    start_positions=(0.1, -0.2, 0.0),
):
    return namespace(
        error_code=namespace(val=1),
        trajectory_start=namespace(joint_state=namespace(name=list(start_names), position=list(start_positions))),
        planned_trajectory=namespace(
            joint_trajectory=namespace(joint_names=["j1", "j2"], points=list(points)),
            multi_dof_joint_trajectory=namespace(
                joint_names=list(multi_names),
                points=list(multi_points),
            ),
        ),
    )


class FakeMoveGroupTransport:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def send_goal(self, goal, timeout_s):
        self.calls.append((goal, timeout_s))
        return self.result


def test_goal_builder_forces_plan_only_and_controlled_request_shape():
    goal = build_move_group_goal(request(), message_types=MESSAGE_TYPES)

    assert goal.request.group_name == "arm"
    assert goal.request.pipeline_id == "ompl"
    assert goal.request.start_state.joint_state.name == ["j1", "j2", "gripper"]
    assert goal.request.start_state.joint_state.position == [0.1, -0.2, 0.0]
    assert goal.request.start_state.is_diff is False
    assert goal.planning_options.plan_only is True
    assert goal.planning_options.look_around is False
    assert goal.planning_options.replan is False
    assert goal.planning_options.replan_attempts == 0
    assert goal.planning_options.replan_delay == 0.0
    constraints = goal.request.goal_constraints[0]
    position = constraints.position_constraints[0]
    orientation = constraints.orientation_constraints[0]
    assert position.header.frame_id == "world"
    assert position.link_name == "tcp"
    assert position.constraint_region.primitives[0].type == 2
    assert position.constraint_region.primitives[0].dimensions == [0.005]
    assert orientation.header.frame_id == "world"
    assert orientation.link_name == "tcp"
    assert orientation.absolute_x_axis_tolerance == 0.05
    assert orientation.absolute_y_axis_tolerance == 0.05
    assert orientation.absolute_z_axis_tolerance == 0.05


def test_adapter_sends_exactly_one_move_group_goal_and_normalizes_result():
    transport = FakeMoveGroupTransport(move_group_result())
    adapter = MoveGroupPlanningAdapter(transport, timeout_s=2.0, message_types=MESSAGE_TYPES)

    result = adapter.plan_only(request())

    assert len(transport.calls) == 1
    sent_goal, timeout = transport.calls[0]
    assert isinstance(sent_goal, GoalMessage)
    assert timeout == 2.0
    assert result.moveit_error_code == 1
    assert result.trajectory_start == (("j1", 0.1), ("j2", -0.2), ("gripper", 0.0))
    assert result.trajectory is not None
    assert result.multi_dof_joint_count == 0


@pytest.mark.parametrize(
    "start_names",
    [
        ("j1", "j2", "gripper", "unexpected"),
        ("j2", "j1", "gripper"),
    ],
)
def test_adapter_rejects_raw_moveit_start_state_with_extra_or_reordered_joint(start_names):
    positions = tuple(0.0 for _name in start_names)
    adapter = MoveGroupPlanningAdapter(
        FakeMoveGroupTransport(move_group_result(start_names=start_names, start_positions=positions)),
        message_types=MESSAGE_TYPES,
    )

    with pytest.raises(PlanningAdapterError, match="joint identity mismatch"):
        adapter.plan_only(request())


def test_empty_and_multi_dof_results_are_preserved_for_bridge_rejection():
    empty = MoveGroupPlanningAdapter(
        FakeMoveGroupTransport(move_group_result(points=())),
        message_types=MESSAGE_TYPES,
    ).plan_only(request())
    multi = MoveGroupPlanningAdapter(
        FakeMoveGroupTransport(move_group_result(multi_names=("floating",), multi_points=(object(),))),
        message_types=MESSAGE_TYPES,
    ).plan_only(request())

    assert empty.trajectory is None
    assert multi.multi_dof_joint_count == 2


def test_malformed_move_group_result_is_adapter_error():
    adapter = MoveGroupPlanningAdapter(FakeMoveGroupTransport(namespace()), message_types=MESSAGE_TYPES)

    with pytest.raises(PlanningAdapterError, match="malformed MoveGroup result"):
        adapter.plan_only(request())


@pytest.mark.parametrize(
    "stamp",
    [namespace(), namespace(sec=True, nanosec=0), namespace(sec=0, nanosec=1_000_000_000)],
)
def test_readiness_rejects_missing_or_malformed_ros_timestamps(stamp):
    with pytest.raises(ReadinessError, match="timestamp"):
        _stamp_ns(stamp)


def test_readiness_rejects_missing_joint_state_before_other_io():
    adapter = object.__new__(RosReadinessAdapter)
    adapter._latest_joint_state = None
    adapter._latest_joint_state_observed_at_ns = None
    adapter._latest_joint_state_clock = None
    adapter._latest_joint_state_publisher_gid = None
    adapter._callback_error = None

    with pytest.raises(ReadinessError, match="joint state unavailable"):
        adapter._build_snapshot()


def test_readiness_rejects_missing_hash_inputs(tmp_path):
    adapter = object.__new__(RosReadinessAdapter)
    adapter._share = tmp_path

    with pytest.raises(ReadinessError, match="config hash input missing"):
        adapter._component_hashes("<robot/>")


def test_readiness_rejects_invalid_controller_and_planning_config(tmp_path):
    (tmp_path / "controllers.yaml").write_text("controller_manager: {}\n", encoding="utf-8")
    moveit = tmp_path / "moveit"
    moveit.mkdir()
    (moveit / "joint_limits.yaml").write_text("default_velocity_scaling_factor: bad\n", encoding="utf-8")

    with pytest.raises(ReadinessError, match="controller configuration unavailable"):
        _controller_identity(tmp_path, "arm_controller", ("j1",))
    with pytest.raises(ReadinessError, match="planning profile unavailable"):
        _planning_profile(tmp_path)


def _ready_snapshot_adapter(monkeypatch):
    adapter = object.__new__(RosReadinessAdapter)
    arm = namespace(
        model="arm",
        planning_group="arm",
        base_frame="world",
        ik_tip_link="tcp",
        joints=("j1",),
        arm_trajectory_controller="arm_controller",
        vendor_description_pkg="vendor_description",
    )
    stamp = namespace(sec=1, nanosec=0)
    transform = namespace(
        header=namespace(stamp=stamp),
        transform=namespace(
            translation=namespace(x=0.0, y=0.0, z=0.0),
            rotation=namespace(x=0.0, y=0.0, z=0.0, w=1.0),
        ),
    )
    adapter._arm = arm
    adapter._max_age_ns = 1_000_000_000
    adapter._timeout_s = 1.0
    adapter._latest_joint_state = namespace(name=["j1"], position=[0.0], header=namespace(stamp=stamp))
    adapter._latest_joint_state_observed_at_ns = 1_000_000_000
    adapter._latest_joint_state_clock = (999_999_900, 999_999_950)
    adapter._latest_joint_state_publisher_gid = b"joint"
    adapter._provenance_armed_at_ns = 999_999_800
    adapter._tf_messages = [("/tf", transform, (999_999_900, 999_999_950), b"tf")]
    adapter._callback_error = None
    adapter._node = namespace(get_clock=lambda: namespace(now=lambda: namespace(nanoseconds=1_000_000_000)))
    adapter._tf_buffer = namespace(
        lookup_transform=lambda *_args: transform,
    )
    adapter._transform_exception = RuntimeError
    adapter._share = Path(".")
    monkeypatch.setitem(sys.modules, "rclpy.time", namespace(Time=lambda: object()))
    monkeypatch.setattr(
        ros_adapter_module,
        "_prove_source_clock_domain",
        lambda *args, **kwargs: _graph_clock_proof_result(),
    )
    monkeypatch.setattr(
        ros_adapter_module,
        "_controller_identity",
        lambda *args: ControllerIdentity("arm_controller", ("j1",), ("position",)),
    )
    monkeypatch.setattr(
        ros_adapter_module, "_planning_profile", lambda *args: PlanningProfile("ompl", "", 1, 1.0, 0.1, 0.1)
    )
    monkeypatch.setattr(
        ros_adapter_module,
        "build_preflight_context",
        lambda: namespace(
            expected_joint_names=("j1",),
            policy=namespace(version="v"),
            effective_limits_sha256="sha256:" + "2" * 64,
            context_sha256="sha256:" + "3" * 64,
        ),
    )
    monkeypatch.setattr(
        adapter,
        "_robot_description",
        lambda: '<robot><joint name="j1" type="revolute"><parent link="base"/><child link="tip"/></joint></robot>',
    )
    monkeypatch.setattr(
        adapter,
        "_component_hashes",
        lambda _description: (
            ("robot_description", "sha256:" + "4" * 64),
            *tuple(
                (name, "sha256:" + "4" * 64)
                for name in (
                    "arm.yaml",
                    "workbench_arm.srdf",
                    "kinematics.yaml",
                    "ompl_planning.yaml",
                    "moveit_joint_limits.yaml",
                    "controllers.yaml",
                    "trajectory_preflight.yaml",
                    "joint_limits.hw_override.yaml",
                )
            ),
        ),
    )
    monkeypatch.setattr(ros_adapter_module, "_package_version", lambda _package: "1")
    return adapter


def test_build_snapshot_success_path_binds_actual_joint_and_tf_sample_clocks(monkeypatch):
    adapter = _ready_snapshot_adapter(monkeypatch)

    snapshot = adapter._build_snapshot()

    assert snapshot.clock_proof_sha256.startswith("sha256:")
    assert snapshot.clock_proof_sha256 != "sha256:" + "1" * 64
    assert snapshot.joint_state_timestamp_clock_id == "ros:1:system"
    assert snapshot.current_joint_positions == (("j1", 0.0),)


def test_snapshot_configuration_hash_covers_all_planning_package_versions(monkeypatch):
    adapter = _ready_snapshot_adapter(monkeypatch)

    snapshot = adapter._build_snapshot()

    versions = dict(snapshot.package_versions)
    assert {
        "moveit_planners_ompl",
        "moveit_kinematics",
        "trac_ik_kinematics_plugin",
        "robotiq_description",
    } <= versions.keys()


def test_planning_package_version_change_changes_configuration_hash(monkeypatch):
    adapter = _ready_snapshot_adapter(monkeypatch)
    original = adapter._build_snapshot()
    monkeypatch.setattr(
        ros_adapter_module,
        "_package_version",
        lambda package: "2" if package == "moveit_kinematics" else "1",
    )

    changed = adapter._build_snapshot()

    assert changed.config_sha256 != original.config_sha256


def test_configuration_recheck_does_not_reuse_joint_tf_freshness_path(monkeypatch):
    adapter = _ready_snapshot_adapter(monkeypatch)
    adapter._last_readiness = adapter._build_snapshot()
    expected = adapter._last_readiness.config_sha256
    monkeypatch.setattr(
        ros_adapter_module,
        "_prove_source_clock_domain",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not recapture sample provenance")),
    )

    assert adapter.configuration_sha256() == expected


def test_acceptance_evidence_exposes_the_actual_bound_sample_proof(monkeypatch):
    adapter = _ready_snapshot_adapter(monkeypatch)
    adapter._last_readiness = adapter._build_snapshot()

    evidence = adapter.acceptance_evidence()

    assert evidence["clock_proof"]["joint_sample"]["publisher_gid"] == b"joint".hex()
    assert evidence["clock_proof"]["joint_sample"]["source_timestamp_ns"] == 999_999_900
    assert evidence["clock_proof"]["joint_sample"]["received_timestamp_ns"] == 999_999_950
    graph_proof = evidence["clock_proof"]["graph_proof"]
    assert sha256_bytes(canonical_json_bytes(graph_proof)) == evidence["clock_proof"]["graph_proof_sha256"]
    assert evidence["component_hashes"]["robot_description"].startswith("sha256:")
    assert evidence["package_versions"]["workbench_motion"] == "1"


def test_sample_clock_proof_rejects_tampered_inner_graph_proof_hash():
    with pytest.raises(ReadinessError, match="graph clock proof hash mismatch"):
        _bind_sample_clock_proof(
            domain_id="ros:1:system",
            graph_proof_sha256="sha256:" + "0" * 64,
            graph_proof={"schema_version": "c3a-clock-proof-1"},
            checked_at_ns=2,
            max_age_ns=1,
            joint_header_ns=1,
            joint_clock=(1, 1),
            joint_publisher_gid=b"joint",
            tf_samples=(("/tf", 1, (1, 1), b"tf"),),
            proven_gids={"/joint_states": frozenset({b"joint"}), "/tf": frozenset({b"tf"})},
            selected_transform_header_ns=1,
            provenance_armed_at_ns=0,
        )


def test_build_snapshot_config_failure_is_readiness_unavailable(monkeypatch):
    adapter = _ready_snapshot_adapter(monkeypatch)
    monkeypatch.setattr(
        ros_adapter_module,
        "_controller_identity",
        lambda *args: (_ for _ in ()).throw(
            ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "controller config failed")
        ),
    )

    with pytest.raises(ReadinessError, match="controller config failed"):
        adapter._build_snapshot()


def test_build_snapshot_package_version_failure_is_readiness_unavailable(monkeypatch):
    adapter = _ready_snapshot_adapter(monkeypatch)
    monkeypatch.setattr(
        ros_adapter_module,
        "_package_version",
        lambda _package: (_ for _ in ()).throw(
            ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "package version failed")
        ),
    )

    with pytest.raises(ReadinessError, match="package version failed"):
        adapter._build_snapshot()


@pytest.mark.parametrize("source", ["joint", "tf"])
def test_build_snapshot_rejects_actual_samples_from_incomparable_clocks(monkeypatch, source):
    adapter = _ready_snapshot_adapter(monkeypatch)
    if source == "joint":
        adapter._latest_joint_state_clock = (2_000_000_000, 2_000_000_100)
    else:
        transform = adapter._tf_messages[0][1]
        adapter._tf_messages = [("/tf", transform, (2_000_000_000, 2_000_000_100), b"tf")]

    with pytest.raises(ReadinessError, match="sample clock is incomparable"):
        adapter._build_snapshot()


@pytest.mark.parametrize("source", ["joint", "tf"])
def test_build_snapshot_rejects_sample_if_its_receive_time_graph_disappeared(monkeypatch, source):
    adapter = _ready_snapshot_adapter(monkeypatch)
    if source == "joint":
        adapter._latest_joint_state_publisher_gid = b"temporary"
    else:
        topic, transform, clock, _gids = adapter._tf_messages[0]
        adapter._tf_messages = [(topic, transform, clock, b"temporary")]

    with pytest.raises(ReadinessError, match="writer GID is no longer proven"):
        adapter._build_snapshot()


def test_build_snapshot_tf_failure_is_readiness_unavailable():
    adapter = object.__new__(RosReadinessAdapter)
    adapter._latest_joint_state = namespace(
        name=["j1"], position=[0.0], header=namespace(stamp=namespace(sec=1, nanosec=0))
    )
    adapter._latest_joint_state_observed_at_ns = 1
    adapter._latest_joint_state_clock = (1_000_000_000, 1_000_000_100)
    adapter._latest_joint_state_publisher_gid = b"joint"
    adapter._arm = namespace(joints=("j1",), base_frame="world", ik_tip_link="tcp")
    adapter._timeout_s = 1.0
    adapter._tf_messages = [("/tf", object(), (1_000_000_000, 1_000_000_100), b"tf")]
    adapter._callback_error = None
    adapter._node = namespace(get_clock=lambda: namespace(now=lambda: namespace(nanoseconds=1)))
    adapter._transform_exception = RuntimeError
    adapter._tf_buffer = namespace(lookup_transform=lambda *_args: (_ for _ in ()).throw(RuntimeError("missing")))
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setitem(sys.modules, "rclpy.time", namespace(Time=lambda: object()))
    monkeypatch.setattr(
        ros_adapter_module,
        "_prove_source_clock_domain",
        lambda *args, **kwargs: _graph_clock_proof_result(),
    )
    try:
        with pytest.raises(ReadinessError, match="TF unavailable"):
            adapter._build_snapshot()
    finally:
        monkeypatch.undo()


def test_snapshot_retries_readiness_failures_until_success(monkeypatch):
    adapter = object.__new__(RosReadinessAdapter)
    adapter._node = namespace(get_logger=lambda: namespace(info=lambda _message: None, error=lambda _message: None))
    adapter._timeout_s = 1.0
    outcomes = [ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "not yet"), object()]
    monkeypatch.setattr(
        adapter,
        "_build_snapshot",
        lambda: (_ for _ in ()).throw(outcomes.pop(0)) if len(outcomes) == 2 else outcomes.pop(0),
    )
    fake_rclpy = namespace(spin_once=lambda *_args, **_kwargs: None)
    monkeypatch.setitem(sys.modules, "rclpy", fake_rclpy)

    result = adapter.snapshot()

    assert result is not None
    assert outcomes == []


def test_snapshot_deadline_returns_last_readiness_failure(monkeypatch):
    adapter = object.__new__(RosReadinessAdapter)
    adapter._node = namespace(get_logger=lambda: namespace(info=lambda _message: None, error=lambda _message: None))
    adapter._timeout_s = 0.1
    monkeypatch.setattr(
        adapter,
        "_build_snapshot",
        lambda: (_ for _ in ()).throw(ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "still missing")),
    )
    fake_rclpy = namespace(spin_once=lambda *_args, **_kwargs: None)
    monkeypatch.setitem(sys.modules, "rclpy", fake_rclpy)
    ticks = iter((0.0, 0.0, 0.2))
    monkeypatch.setattr(ros_adapter_module.time, "monotonic", lambda: next(ticks, 0.2))

    with pytest.raises(ReadinessError, match="still missing"):
        adapter.snapshot()


class _ParameterValue:
    type = 1

    def __init__(self, value):
        self.bool_value = value


class _ParameterFuture:
    def __init__(self, value):
        self._value = value

    def done(self):
        return True

    def result(self):
        return namespace(values=[_ParameterValue(self._value)])


class _ParameterClient:
    values: ClassVar[dict[str, bool]] = {}

    def __init__(self, _node, publisher):
        self.publisher = publisher

    def wait_for_services(self, timeout_sec):
        return self.publisher in self.values

    def get_parameters(self, _names):
        return _ParameterFuture(self.values[self.publisher])


def test_clock_proof_requires_all_source_publishers_and_matching_sim_time():
    node = namespace(
        get_parameter=lambda name: namespace(value=False),
        get_clock=lambda: namespace(clock_type=1),
        get_publishers_info_by_topic=lambda topic: (
            [
                namespace(node_name="joint_pub", node_namespace="/", endpoint_gid=b"joint"),
            ]
            if topic == "/joint_states"
            else [namespace(node_name="tf_pub", node_namespace="/", endpoint_gid=topic.encode())]
        ),
    )
    _ParameterClient.values = {"/joint_pub": False, "/tf_pub": False}

    domain, proof_sha256, gids, proof = _prove_source_clock_domain(
        node,
        timeout_s=1.0,
        expected_publishers={
            "/joint_states": ("/joint_pub",),
            "/tf": ("/tf_pub",),
            "/tf_static": ("/tf_pub",),
        },
        parameter_client_factory=_ParameterClient,
        spin_until_future_complete=lambda *_args, **_kwargs: None,
    )

    assert domain == "ros:1:system"
    assert proof_sha256 == sha256_bytes(canonical_json_bytes(proof))
    assert proof["publisher_use_sim_time"] == {"/joint_pub": False, "/tf_pub": False}
    assert gids["/joint_states"] == frozenset({b"joint"})


def test_provenance_payload_requires_sample_writer_gid_and_closed_schema(tmp_path):
    path = tmp_path / "provenance.json"
    payload = {
        "schema_version": "c3a-rmw-sample-provenance-1",
        "armed_at_ns": 1,
        "joint_state": {
            "publisher_name": "/joint_state_publisher",
            "publisher_gid": "01" * 16,
            "source_timestamp_ns": 1,
            "received_timestamp_ns": 2,
            "publication_sequence_number": 3,
            "header": {"sec": 0, "nanosec": 1},
            "name": ["j1"],
            "position": [0.0],
        },
        "tf": {
            "publisher_name": "/robot_state_publisher",
            "publisher_gid": "02" * 16,
            "source_timestamp_ns": 1,
            "received_timestamp_ns": 2,
            "publication_sequence_number": 3,
            "transforms": [],
        },
        "tf_static": {
            "publisher_name": "/robot_state_publisher",
            "publisher_gid": "03" * 16,
            "source_timestamp_ns": 1,
            "received_timestamp_ns": 2,
            "publication_sequence_number": 3,
            "transforms": [],
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert _read_provenance_payload(path)["joint_state"]["publisher_gid"] == "01" * 16

    payload["joint_state"]["unknown"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReadinessError, match="closed schema"):
        _read_provenance_payload(path)


def test_provenance_payload_rejects_missing_or_malformed_writer_gid(tmp_path):
    path = tmp_path / "provenance.json"
    identity = {
        "publisher_name": "/joint_state_publisher",
        "publisher_gid": "bad",
        "source_timestamp_ns": 1,
        "received_timestamp_ns": 2,
        "publication_sequence_number": 3,
    }
    path.write_text(
        json.dumps(
            {
                "schema_version": "c3a-rmw-sample-provenance-1",
                "armed_at_ns": 1,
                "joint_state": {**identity, "header": {}, "name": [], "position": []},
                "tf": {
                    **identity,
                    "publisher_name": "/robot_state_publisher",
                    "publisher_gid": "01" * 16,
                    "transforms": [],
                },
                "tf_static": {
                    **identity,
                    "publisher_name": "/robot_state_publisher",
                    "publisher_gid": "02" * 16,
                    "transforms": [],
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ReadinessError, match="provenance identity"):
        _read_provenance_payload(path)


def test_provenance_payload_rejects_joint_or_dynamic_tf_received_before_collector_armed(tmp_path):
    path = tmp_path / "provenance.json"
    payload = _complete_provenance_payload()
    payload["armed_at_ns"] = payload["joint_state"]["received_timestamp_ns"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ReadinessError, match="predates provenance marker arm time"):
        _read_provenance_payload(path)


def _complete_provenance_payload():
    transform = {
        "header": {"sec": 1, "nanosec": 2, "frame_id": "world"},
        "child_frame_id": "tcp",
        "translation": [0.1, 0.2, 0.3],
        "rotation": [0.0, 0.0, 0.0, 1.0],
    }
    return {
        "schema_version": "c3a-rmw-sample-provenance-1",
        "armed_at_ns": 1_000_000_000,
        "joint_state": {
            "publisher_name": "/joint_state_publisher",
            "publisher_gid": "01" * 16,
            "source_timestamp_ns": 1_000_000_001,
            "received_timestamp_ns": 1_000_000_002,
            "publication_sequence_number": 3,
            "header": {"sec": 1, "nanosec": 1},
            "name": ["j1"],
            "position": [0.25],
        },
        "tf": {
            "publisher_name": "/robot_state_publisher",
            "publisher_gid": "02" * 16,
            "source_timestamp_ns": 1_000_000_002,
            "received_timestamp_ns": 1_000_000_003,
            "publication_sequence_number": 4,
            "transforms": [transform],
        },
        "tf_static": {
            "publisher_name": "/robot_state_publisher",
            "publisher_gid": "03" * 16,
            "source_timestamp_ns": 1_000_000_002,
            "received_timestamp_ns": 1_000_000_003,
            "publication_sequence_number": 5,
            "transforms": [transform],
        },
    }


class _JointStateMessage:
    def __init__(self):
        self.header = namespace(stamp=namespace(sec=0, nanosec=0))
        self.name = []
        self.position = []


class _TransformMessage:
    def __init__(self):
        self.header = namespace(stamp=namespace(sec=0, nanosec=0), frame_id="")
        self.child_frame_id = ""
        self.transform = namespace(
            translation=namespace(x=0.0, y=0.0, z=0.0),
            rotation=namespace(x=0.0, y=0.0, z=0.0, w=0.0),
        )


def test_load_provenance_reconstructs_actual_joint_and_tf_samples(tmp_path):
    path = tmp_path / "provenance.json"
    path.write_text(json.dumps(_complete_provenance_payload()), encoding="utf-8")
    adapter = object.__new__(RosReadinessAdapter)
    adapter._timeout_s = 0.1
    dynamic = []
    static = []
    adapter._tf_buffer = namespace(
        set_transform=lambda transform, authority: dynamic.append((transform, authority)),
        set_transform_static=lambda transform, authority: static.append((transform, authority)),
    )

    adapter._load_provenance(path, joint_state_type=_JointStateMessage, transform_type=_TransformMessage)

    assert adapter._latest_joint_state.name == ["j1"]
    assert adapter._latest_joint_state.position == [0.25]
    assert adapter._latest_joint_state_publisher_gid == bytes.fromhex("01" * 16)
    assert adapter._provenance_armed_at_ns == 1_000_000_000
    assert [topic for topic, *_rest in adapter._tf_messages] == ["/tf", "/tf_static"]
    assert len(dynamic) == 1
    assert len(static) == 1


def test_load_provenance_rejects_malformed_tf_geometry(tmp_path):
    path = tmp_path / "provenance.json"
    payload = _complete_provenance_payload()
    payload["tf"]["transforms"][0]["rotation"] = [0.0, 1.0]
    path.write_text(json.dumps(payload), encoding="utf-8")
    adapter = object.__new__(RosReadinessAdapter)
    adapter._timeout_s = 0.1
    adapter._tf_buffer = namespace(set_transform=lambda *_args: None, set_transform_static=lambda *_args: None)

    with pytest.raises(ReadinessError, match="TF provenance transform is malformed"):
        adapter._load_provenance(path, joint_state_type=_JointStateMessage, transform_type=_TransformMessage)


def test_wait_for_provenance_is_bounded_when_artifact_never_arrives(tmp_path, monkeypatch):
    ticks = iter((0.0, 0.0, 0.2))
    monkeypatch.setattr(ros_adapter_module.time, "monotonic", lambda: next(ticks, 0.2))
    monkeypatch.setattr(ros_adapter_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(ReadinessError, match="sample provenance unavailable"):
        _wait_for_provenance_payload(tmp_path / "missing.json", 0.1)


def test_clock_proof_rejects_mismatched_source_publisher_clock():
    node = namespace(
        get_parameter=lambda name: namespace(value=False),
        get_clock=lambda: namespace(clock_type=1),
        get_publishers_info_by_topic=lambda _topic: [
            namespace(node_name="pub", node_namespace="/", endpoint_gid=b"pub")
        ],
    )
    _ParameterClient.values = {"/pub": True}

    with pytest.raises(ReadinessError, match="clock domains"):
        _prove_source_clock_domain(
            node,
            timeout_s=1.0,
            expected_publishers={topic: ("/pub",) for topic in ("/joint_states", "/tf", "/tf_static")},
            parameter_client_factory=_ParameterClient,
            spin_until_future_complete=lambda *_args, **_kwargs: None,
        )


def test_clock_proof_rejects_unknown_source_publisher():
    node = namespace(
        get_parameter=lambda name: namespace(value=False),
        get_clock=lambda: namespace(clock_type=1),
        get_publishers_info_by_topic=lambda _topic: [
            namespace(node_name="unexpected", node_namespace="/", endpoint_gid=b"unexpected")
        ],
    )

    with pytest.raises(ReadinessError, match="uncontrolled clock source"):
        _prove_source_clock_domain(
            node,
            timeout_s=1.0,
            expected_publishers={topic: ("/expected",) for topic in ("/joint_states", "/tf", "/tf_static")},
            parameter_client_factory=_ParameterClient,
            spin_until_future_complete=lambda *_args, **_kwargs: None,
        )


def test_adapter_rejects_wrong_request_type_before_transport():
    transport = FakeMoveGroupTransport(move_group_result())
    adapter = MoveGroupPlanningAdapter(transport, message_types=MESSAGE_TYPES)

    with pytest.raises(PlanningAdapterError, match="requires PlanningRequest"):
        adapter.plan_only({})
    assert transport.calls == []


def test_production_transport_action_name_is_not_caller_overridable():
    with pytest.raises(ValueError, match="action name is fixed"):
        RclpyMoveGroupTransport(object(), "/caller_selected_action")


class FakeFuture:
    def __init__(self, *, done=True, value=None, error=None):
        self._done = done
        self._value = value
        self._error = error

    def done(self):
        return self._done

    def result(self):
        if self._error is not None:
            raise self._error
        return self._value


class FakeHandle:
    def __init__(self, *, accepted=True, result_future=None, cancel_future=None):
        self.accepted = accepted
        self.result_future = result_future
        self.cancel_future = cancel_future or FakeFuture(value=object())
        self.cancelled = False

    def get_result_async(self):
        return self.result_future

    def cancel_goal_async(self):
        self.cancelled = True
        return self.cancel_future


class FakeActionClient:
    instance = None

    def __init__(self, _node, _action, _name):
        self.wait_result = True
        self.goal_future = FakeFuture(value=FakeHandle())
        self.result_future = FakeFuture(value=namespace(result=object()))
        self.goal = None
        FakeActionClient.instance = self

    def wait_for_server(self, timeout_sec):
        self.wait_timeout = timeout_sec
        return self.wait_result

    def send_goal_async(self, goal):
        self.goal = goal
        handle = self.goal_future.result()
        if handle is not None and handle.result_future is None:
            handle.result_future = self.result_future
        return self.goal_future


def fake_transport(monkeypatch):
    rclpy = types.ModuleType("rclpy")
    rclpy.spin_until_future_complete = lambda _node, _future, timeout_sec: None
    action = types.ModuleType("rclpy.action")
    action.ActionClient = FakeActionClient
    rclpy.action = action
    moveit_msgs = types.ModuleType("moveit_msgs")
    moveit_action = types.ModuleType("moveit_msgs.action")
    moveit_action.MoveGroup = type("MoveGroup", (), {})
    moveit_msgs.action = moveit_action
    monkeypatch.setitem(sys.modules, "rclpy", rclpy)
    monkeypatch.setitem(sys.modules, "rclpy.action", action)
    monkeypatch.setitem(sys.modules, "moveit_msgs", moveit_msgs)
    monkeypatch.setitem(sys.modules, "moveit_msgs.action", moveit_action)
    return RclpyMoveGroupTransport(object())


def test_transport_reports_server_unavailable(monkeypatch):
    transport = fake_transport(monkeypatch)
    FakeActionClient.instance.wait_result = False

    with pytest.raises(PlanningServerUnavailable):
        transport.send_goal(object(), 1.0)


def test_transport_reports_goal_response_timeout(monkeypatch):
    transport = fake_transport(monkeypatch)
    FakeActionClient.instance.goal_future = FakeFuture(done=False)

    with pytest.raises(PlanningTimedOut, match="goal response"):
        transport.send_goal(object(), 1.0)


def test_transport_reports_goal_rejection_as_adapter_error(monkeypatch):
    transport = fake_transport(monkeypatch)
    FakeActionClient.instance.goal_future = FakeFuture(value=FakeHandle(accepted=False))

    with pytest.raises(PlanningAdapterError, match="rejected"):
        transport.send_goal(object(), 1.0)


def test_transport_cancels_and_reports_result_timeout(monkeypatch):
    transport = fake_transport(monkeypatch)
    handle = FakeHandle(result_future=FakeFuture(done=False))
    FakeActionClient.instance.goal_future = FakeFuture(value=handle)

    with pytest.raises(PlanningTimedOut, match="planning timed out"):
        transport.send_goal(object(), 1.0)
    assert handle.cancelled is True


def test_transport_rejects_unacknowledged_cancellation(monkeypatch):
    transport = fake_transport(monkeypatch)
    handle = FakeHandle(result_future=FakeFuture(done=False), cancel_future=FakeFuture(done=False))
    FakeActionClient.instance.goal_future = FakeFuture(value=handle)

    with pytest.raises(PlanningTimedOut, match="cancellation acknowledgement timed out"):
        transport.send_goal(object(), 1.0)


def test_transport_requires_terminal_state_after_cancellation(monkeypatch):
    transport = fake_transport(monkeypatch)
    handle = FakeHandle(result_future=FakeFuture(done=False))
    FakeActionClient.instance.goal_future = FakeFuture(value=handle)

    with pytest.raises(PlanningTimedOut, match="terminal state"):
        transport.send_goal(object(), 1.0)


def test_transport_waits_for_cancel_acknowledgement_and_terminal_state(monkeypatch):
    transport = fake_transport(monkeypatch)
    handle = FakeHandle(
        result_future=FakeFuture(done=False),
        cancel_future=FakeFuture(done=True, value=namespace(return_code=0)),
    )
    FakeActionClient.instance.goal_future = FakeFuture(value=handle)

    with pytest.raises(PlanningTimedOut, match="planning timed out"):
        transport.send_goal(object(), 1.0)
    assert handle.cancelled is True


def test_transport_reports_malformed_result_as_adapter_error(monkeypatch):
    transport = fake_transport(monkeypatch)
    handle = FakeHandle(result_future=FakeFuture(value=None))
    FakeActionClient.instance.goal_future = FakeFuture(value=handle)

    with pytest.raises(PlanningAdapterError, match="result failed"):
        transport.send_goal(object(), 1.0)


def test_ros_adapter_source_creates_no_execution_or_controller_transport():
    source_path = Path(__file__).parents[1] / "workbench_motion" / "c3a_ros_adapter.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {
        alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names
    }
    calls = {
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "control_msgs" not in imports
    assert "trajectory_msgs" not in imports
    assert "create_publisher" not in calls
    assert "create_client" not in calls
