"""ROS adapters behind the C3a plan-only module's internal seams.

This module creates only a ``moveit_msgs/action/MoveGroup`` client.  It has no
ExecuteTrajectory, FollowJointTrajectory, controller-topic, or gripper client.
"""

from __future__ import annotations

import json
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

import yaml

from workbench_motion.arm_config import load_arm_config
from workbench_motion.c3a_bridge import seal_readiness, validate_readiness
from workbench_motion.c3a_types import (
    ControllerIdentity,
    DiagnosticCode,
    PlanningAdapterError,
    PlanningProfile,
    PlanningRequest,
    PlanningResponse,
    PlanningServerUnavailable,
    PlanningTimedOut,
    ReadinessError,
    ReadinessSnapshot,
    TransformSnapshot,
    canonical_json_bytes,
    sha256_bytes,
)
from workbench_motion.joint_limits import PreflightContext, build_preflight_context

_LOGGER = logging.getLogger(__name__)


class MoveGroupTransport(Protocol):
    def send_goal(self, goal: object, timeout_s: float) -> object: ...


@dataclass(frozen=True, slots=True)
class _MessageTypes:
    goal: type
    constraints: type
    position_constraint: type
    orientation_constraint: type
    solid_primitive: type
    pose: type


@dataclass(frozen=True, slots=True)
class _ConfigurationFacts:
    controller: ControllerIdentity
    planning_profile: PlanningProfile
    preflight_context: PreflightContext
    component_hashes: tuple[tuple[str, str], ...]
    package_versions: tuple[tuple[str, str], ...]


_CLOCK_SOURCE_TOPICS = ("/joint_states", "/tf", "/tf_static")
_HARNESS_CLOCK_PUBLISHERS = {
    "/joint_states": ("/joint_state_publisher",),
    "/tf": ("/robot_state_publisher",),
    "/tf_static": ("/robot_state_publisher",),
}
_IDENTITY_KEYS = {
    "publisher_name",
    "publisher_gid",
    "source_timestamp_ns",
    "received_timestamp_ns",
    "publication_sequence_number",
}


def _require_closed_keys(value: object, expected: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, f"{label} violates closed schema")
    return value


def _validate_provenance_identity(value: dict[str, object], expected_publisher: str) -> None:
    publisher = value.get("publisher_name")
    gid = value.get("publisher_gid")
    source = value.get("source_timestamp_ns")
    received = value.get("received_timestamp_ns")
    sequence = value.get("publication_sequence_number")
    if (
        publisher != expected_publisher
        or not isinstance(gid, str)
        or len(gid) != 32
        or any(character not in "0123456789abcdef" for character in gid)
        or isinstance(source, bool)
        or isinstance(received, bool)
        or isinstance(sequence, bool)
        or not isinstance(source, int)
        or not isinstance(received, int)
        or not isinstance(sequence, int)
        or source <= 0
        or received < source
        or sequence < 0
    ):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "sample provenance identity is malformed")


def _read_provenance_payload(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, f"sample provenance unavailable: {exc}") from exc
    root = _require_closed_keys(
        payload, {"schema_version", "armed_at_ns", "joint_state", "tf", "tf_static"}, "provenance"
    )
    if root["schema_version"] != "c3a-rmw-sample-provenance-1":
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "sample provenance schema is unsupported")
    joint = _require_closed_keys(
        root["joint_state"], _IDENTITY_KEYS | {"header", "name", "position"}, "joint provenance"
    )
    dynamic = _require_closed_keys(root["tf"], _IDENTITY_KEYS | {"transforms"}, "TF provenance")
    static = _require_closed_keys(root["tf_static"], _IDENTITY_KEYS | {"transforms"}, "TF provenance")
    _validate_provenance_identity(joint, "/joint_state_publisher")
    _validate_provenance_identity(dynamic, "/robot_state_publisher")
    _validate_provenance_identity(static, "/robot_state_publisher")
    armed_at_ns = root["armed_at_ns"]
    if isinstance(armed_at_ns, bool) or not isinstance(armed_at_ns, int) or armed_at_ns <= 0:
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "provenance marker arm time is malformed")
    if joint["received_timestamp_ns"] <= armed_at_ns or dynamic["received_timestamp_ns"] <= armed_at_ns:
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "sample predates provenance marker arm time")
    return root


def _wait_for_provenance_payload(path: Path, timeout_s: float) -> dict[str, object]:
    deadline = time.monotonic() + timeout_s
    last_error: ReadinessError | None = None
    while time.monotonic() < deadline:
        try:
            return _read_provenance_payload(path)
        except ReadinessError as exc:
            last_error = exc
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
    if last_error is not None:
        raise last_error
    raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "sample provenance deadline expired")


def _publisher_identity(info: object) -> tuple[str, bytes]:
    try:
        name = info.node_name
        namespace = info.node_namespace
        gid = bytes(info.endpoint_gid)
    except AttributeError as exc:
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "publisher identity is missing") from exc
    if not isinstance(name, str) or not name or not isinstance(namespace, str) or not namespace.startswith("/"):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "publisher identity is malformed")
    if not gid:
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "publisher GID is missing")
    full_name = f"/{name}" if namespace == "/" else f"{namespace.rstrip('/')}/{name}"
    return full_name, gid


def _prove_source_clock_domain(
    node: object,
    *,
    timeout_s: float,
    expected_publishers: dict[str, tuple[str, ...]],
    parameter_client_factory=None,
    spin_until_future_complete=None,
) -> tuple[str, str, dict[str, frozenset[bytes]], dict[str, object]]:
    """Prove every possible joint/TF publisher uses the subscriber's ROS clock domain."""
    if parameter_client_factory is None or spin_until_future_complete is None:
        import rclpy
        from rclpy.parameter_client import AsyncParameterClient

        parameter_client_factory = AsyncParameterClient
        spin_until_future_complete = rclpy.spin_until_future_complete
    try:
        local_use_sim_time = node.get_parameter("use_sim_time").value
        clock_type = int(node.get_clock().clock_type)
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, f"local clock identity unavailable: {exc}") from exc
    if type(local_use_sim_time) is not bool:
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "local use_sim_time is not a declared boolean")
    publishers_by_topic: dict[str, tuple[str, ...]] = {}
    publisher_gids_by_topic: dict[str, frozenset[bytes]] = {}
    try:
        for topic in _CLOCK_SOURCE_TOPICS:
            identities = tuple(_publisher_identity(info) for info in node.get_publishers_info_by_topic(topic))
            publishers = tuple(sorted(name for name, _gid in identities))
            if not publishers:
                raise ReadinessError(
                    DiagnosticCode.READINESS_UNAVAILABLE, f"clock source publishers missing for {topic}"
                )
            if publishers != expected_publishers.get(topic):
                raise ReadinessError(
                    DiagnosticCode.READINESS_UNAVAILABLE,
                    f"uncontrolled clock source publisher set for {topic}",
                )
            publishers_by_topic[topic] = publishers
            publisher_gids_by_topic[topic] = frozenset(gid for _name, gid in identities)
    except (AttributeError, RuntimeError, TypeError) as exc:
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, f"publisher graph unavailable: {exc}") from exc
    deadline = time.monotonic() + timeout_s
    publisher_domains: dict[str, bool] = {}
    for publisher in sorted({name for names in publishers_by_topic.values() for name in names}):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "publisher clock proof timed out")
        client = parameter_client_factory(node, publisher)
        if not client.wait_for_services(timeout_sec=remaining):
            raise ReadinessError(
                DiagnosticCode.READINESS_UNAVAILABLE,
                f"publisher clock parameters unavailable for {publisher}",
            )
        future = client.get_parameters(["use_sim_time"])
        spin_until_future_complete(node, future, timeout_sec=max(0.0, deadline - time.monotonic()))
        if not future.done():
            raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "publisher clock proof timed out")
        try:
            values = future.result().values
            if len(values) != 1 or values[0].type != 1:
                raise ValueError("use_sim_time is not a declared boolean")
            publisher_use_sim_time = values[0].bool_value
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            raise ReadinessError(
                DiagnosticCode.READINESS_UNAVAILABLE,
                f"publisher clock identity malformed for {publisher}: {exc}",
            ) from exc
        if publisher_use_sim_time is not local_use_sim_time:
            raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "publisher clock domains are incomparable")
        publisher_domains[publisher] = publisher_use_sim_time
    domain_id = f"ros:{clock_type}:{'sim' if local_use_sim_time else 'system'}"
    proof = {
        "schema_version": "c3a-clock-proof-1",
        "domain_id": domain_id,
        "publishers_by_topic": {topic: list(names) for topic, names in sorted(publishers_by_topic.items())},
        "publisher_use_sim_time": publisher_domains,
        "publisher_gids_by_topic": {
            topic: [gid.hex() for gid in sorted(gids)] for topic, gids in sorted(publisher_gids_by_topic.items())
        },
    }
    return domain_id, sha256_bytes(canonical_json_bytes(proof)), publisher_gids_by_topic, proof


def _bind_sample_clock_proof(
    *,
    domain_id: str,
    graph_proof_sha256: str,
    graph_proof: dict[str, object],
    checked_at_ns: int,
    max_age_ns: int,
    joint_header_ns: int,
    joint_clock: tuple[int, int],
    joint_publisher_gid: bytes,
    tf_samples: tuple[tuple[str, int, tuple[int, int], bytes], ...],
    proven_gids: dict[str, frozenset[bytes]],
    selected_transform_header_ns: int,
    provenance_armed_at_ns: int,
) -> tuple[str, dict[str, object]]:
    """Bind clock comparability to the actual DDS samples used for readiness."""
    if sha256_bytes(canonical_json_bytes(graph_proof)) != graph_proof_sha256:
        raise ReadinessError(DiagnosticCode.CONTEXT_MISMATCH, "graph clock proof hash mismatch")
    records = (("/joint_states", joint_header_ns, joint_clock, joint_publisher_gid), *tf_samples)
    if not any(topic.startswith("/tf") and header == selected_transform_header_ns for topic, header, _, _ in records):
        raise ReadinessError(
            DiagnosticCode.READINESS_UNAVAILABLE,
            "selected TF is not bound to an observed sample",
        )
    for topic, header_ns, (source_ns, received_ns), publisher_gid in records:
        if publisher_gid not in proven_gids[topic]:
            raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "sample writer GID is no longer proven")
        if abs(header_ns - source_ns) > max_age_ns or source_ns > received_ns or received_ns > checked_at_ns:
            raise ReadinessError(
                DiagnosticCode.READINESS_UNAVAILABLE,
                "sample clock is incomparable with its ROS header",
            )
    joint_received_ns = joint_clock[1]
    if checked_at_ns - joint_received_ns > max_age_ns:
        raise ReadinessError(DiagnosticCode.READINESS_STALE, "joint-state middleware sample is stale")
    proof: dict[str, object] = {
        "schema_version": "c3a-sample-clock-proof-1",
        "domain_id": domain_id,
        "graph_proof_sha256": graph_proof_sha256,
        "graph_proof": graph_proof,
        "checked_at_ns": checked_at_ns,
        "provenance_armed_at_ns": provenance_armed_at_ns,
        "joint_sample": {
            "header_timestamp_ns": joint_header_ns,
            "source_timestamp_ns": joint_clock[0],
            "received_timestamp_ns": joint_clock[1],
            "publisher_gid": joint_publisher_gid.hex(),
        },
        "tf_samples": [
            {
                "topic": topic,
                "header_timestamp_ns": header_ns,
                "source_timestamp_ns": clock[0],
                "received_timestamp_ns": clock[1],
                "publisher_gid": gid.hex(),
            }
            for topic, header_ns, clock, gid in tf_samples
        ],
        "selected_transform_header_ns": selected_transform_header_ns,
    }
    return sha256_bytes(canonical_json_bytes(proof)), proof


def _ros_message_types() -> _MessageTypes:
    try:
        from geometry_msgs.msg import Pose
        from moveit_msgs.action import MoveGroup
        from moveit_msgs.msg import Constraints, OrientationConstraint, PositionConstraint
        from shape_msgs.msg import SolidPrimitive
    except (ImportError, ModuleNotFoundError) as exc:
        raise PlanningAdapterError(f"MoveIt message types unavailable: {exc}") from exc
    return _MessageTypes(
        goal=MoveGroup.Goal,
        constraints=Constraints,
        position_constraint=PositionConstraint,
        orientation_constraint=OrientationConstraint,
        solid_primitive=SolidPrimitive,
        pose=Pose,
    )


def build_move_group_goal(
    request: PlanningRequest,
    *,
    message_types: _MessageTypes | None = None,
) -> object:
    """Translate the controlled request into a forced plan-only MoveGroup goal."""
    if not isinstance(request, PlanningRequest):
        raise PlanningAdapterError("MoveGroup adapter requires PlanningRequest")
    types = _ros_message_types() if message_types is None else message_types
    goal = types.goal()
    motion = goal.request
    motion.group_name = request.planning_group
    motion.pipeline_id = request.pipeline_id
    motion.planner_id = request.planner_id
    motion.num_planning_attempts = request.num_planning_attempts
    motion.allowed_planning_time = request.allowed_planning_time_s
    motion.max_velocity_scaling_factor = request.max_velocity_scaling_factor
    motion.max_acceleration_scaling_factor = request.max_acceleration_scaling_factor
    motion.start_state.joint_state.name = [joint for joint, _value in request.full_start_positions]
    motion.start_state.joint_state.position = [value for _joint, value in request.full_start_positions]
    motion.start_state.is_diff = False

    target_pose = types.pose()
    target_pose.position.x = request.pose.x
    target_pose.position.y = request.pose.y
    target_pose.position.z = request.pose.z
    target_pose.orientation.x = request.pose.qx
    target_pose.orientation.y = request.pose.qy
    target_pose.orientation.z = request.pose.qz
    target_pose.orientation.w = request.pose.qw

    primitive = types.solid_primitive()
    primitive.type = 2  # shape_msgs/SolidPrimitive.SPHERE
    primitive.dimensions = [request.tolerance.position_m]

    position = types.position_constraint()
    position.header.frame_id = request.planning_frame
    position.link_name = request.ik_tip_link
    position.constraint_region.primitives = [primitive]
    position.constraint_region.primitive_poses = [target_pose]
    position.weight = 1.0

    orientation = types.orientation_constraint()
    orientation.header.frame_id = request.planning_frame
    orientation.link_name = request.ik_tip_link
    orientation.orientation = target_pose.orientation
    orientation.absolute_x_axis_tolerance = request.tolerance.orientation_rad
    orientation.absolute_y_axis_tolerance = request.tolerance.orientation_rad
    orientation.absolute_z_axis_tolerance = request.tolerance.orientation_rad
    orientation.weight = 1.0

    constraints = types.constraints()
    constraints.position_constraints = [position]
    constraints.orientation_constraints = [orientation]
    motion.goal_constraints = [constraints]

    goal.planning_options.plan_only = True
    goal.planning_options.look_around = False
    goal.planning_options.replan = False
    goal.planning_options.replan_attempts = 0
    goal.planning_options.replan_delay = 0.0
    return goal


class MoveGroupPlanningAdapter:
    """Planning adapter that permits exactly one MoveGroup goal transport."""

    def __init__(
        self,
        transport: MoveGroupTransport,
        *,
        timeout_s: float = 10.0,
        message_types: _MessageTypes | None = None,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("planning timeout must be positive")
        self._transport = transport
        self._timeout_s = timeout_s
        self._message_types = message_types

    def plan_only(self, request: PlanningRequest) -> PlanningResponse:
        goal = build_move_group_goal(request, message_types=self._message_types)
        result = self._transport.send_goal(goal, self._timeout_s)
        try:
            error_code = int(result.error_code.val)
            joint_state = result.trajectory_start.joint_state
            names = tuple(joint_state.name)
            positions = tuple(joint_state.position)
            if len(names) != len(positions) or len(names) != len(set(names)):
                raise ValueError("trajectory_start joint names/positions length mismatch")
            expected_start = request.full_start_positions
            if names != tuple(joint for joint, _value in expected_start):
                raise ValueError(
                    f"trajectory_start joint identity mismatch: result={names!r} request={expected_start!r}"
                )
            if tuple(float(value) for value in positions) != tuple(value for _joint, value in expected_start):
                raise ValueError("trajectory_start positions mismatch")
            planned = result.planned_trajectory
            multi_dof = planned.multi_dof_joint_trajectory
            multi_dof_count = len(multi_dof.joint_names) + len(multi_dof.points)
            trajectory = planned.joint_trajectory
            if not trajectory.points:
                trajectory = None
            return PlanningResponse(
                moveit_error_code=error_code,
                trajectory_start=tuple(zip(names, positions, strict=True)),
                trajectory=trajectory,
                multi_dof_joint_count=multi_dof_count,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            _LOGGER.error("C3a MoveGroup result rejected: %s", exc)
            raise PlanningAdapterError(f"malformed MoveGroup result: {exc}") from exc


class RclpyMoveGroupTransport:
    """Synchronous transport over the sole C3a ROS action client."""

    def __init__(self, node: object, action_name: str = "/move_action") -> None:
        if action_name != "/move_action":
            raise ValueError("C3a MoveGroup action name is fixed")
        try:
            from moveit_msgs.action import MoveGroup
            from rclpy.action import ActionClient
        except (ImportError, ModuleNotFoundError) as exc:
            raise PlanningAdapterError(f"MoveGroup action support unavailable: {exc}") from exc
        self._node = node
        self._client = ActionClient(node, MoveGroup, action_name)

    def send_goal(self, goal: object, timeout_s: float) -> object:
        import rclpy

        if not self._client.wait_for_server(timeout_sec=timeout_s):
            raise PlanningServerUnavailable()
        goal_future = self._client.send_goal_async(goal)
        rclpy.spin_until_future_complete(self._node, goal_future, timeout_sec=timeout_s)
        if not goal_future.done():
            raise PlanningTimedOut("MoveGroup goal response timed out")
        try:
            handle = goal_future.result()
        except (RuntimeError, TypeError) as exc:
            raise PlanningAdapterError(f"MoveGroup goal response failed: {exc}") from exc
        if handle is None or not handle.accepted:
            raise PlanningAdapterError("MoveGroup goal was rejected by the action server")
        result_future = handle.get_result_async()
        rclpy.spin_until_future_complete(self._node, result_future, timeout_sec=timeout_s)
        if not result_future.done():
            handle.cancel_goal_async()
            raise PlanningTimedOut()
        try:
            wrapped = result_future.result()
            if wrapped is None:
                raise RuntimeError("empty result")
            return wrapped.result
        except (AttributeError, RuntimeError, TypeError) as exc:
            raise PlanningAdapterError(f"MoveGroup result failed: {exc}") from exc


def _stamp_ns(stamp: object) -> int:
    try:
        sec = stamp.sec
        nanosec = stamp.nanosec
    except AttributeError as exc:
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "ROS timestamp is missing") from exc
    if (
        isinstance(sec, bool)
        or isinstance(nanosec, bool)
        or not isinstance(sec, int)
        or not isinstance(nanosec, int)
        or sec < 0
        or not 0 <= nanosec < 1_000_000_000
    ):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "ROS timestamp is malformed")
    return sec * 1_000_000_000 + nanosec


def _package_version(package: str) -> str:
    from ament_index_python.packages import get_package_share_directory

    package_xml = Path(get_package_share_directory(package)) / "package.xml"
    try:
        root = ET.fromstring(package_xml.read_text(encoding="utf-8"))
        version = root.findtext("version")
    except (ET.ParseError, OSError) as exc:
        raise ReadinessError(
            DiagnosticCode.READINESS_UNAVAILABLE,
            f"could not read version for {package}: {exc}",
        ) from exc
    if not version:
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, f"version missing for {package}")
    return version


def _model_ordered_joint_state(
    robot_description: str,
    state: dict[str, object],
) -> tuple[tuple[str, float], ...]:
    try:
        root = ET.fromstring(robot_description)
        children_by_parent: dict[str, list[tuple[str, str]]] = {}
        child_links: set[str] = set()
        for joint in root.findall("joint"):
            parent = joint.find("parent").attrib["link"]
            child = joint.find("child").attrib["link"]
            children_by_parent.setdefault(parent, []).append((child, joint.attrib["name"]))
            child_links.add(child)
        root_links = sorted(set(children_by_parent) - child_links)
        model_order: list[str] = []

        def visit(link: str) -> None:
            for child, joint in sorted(children_by_parent.get(link, [])):
                if joint in state:
                    model_order.append(joint)
                visit(child)

        for link in root_links:
            visit(link)
    except (AttributeError, ET.ParseError, KeyError, TypeError) as exc:
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, f"robot joint order unavailable: {exc}") from exc
    if len(model_order) != len(state) or len(model_order) != len(set(model_order)):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "robot joint order does not cover current state")
    try:
        return tuple((joint, float(state[joint])) for joint in model_order)
    except (TypeError, ValueError) as exc:
        raise ReadinessError(
            DiagnosticCode.READINESS_UNAVAILABLE, f"full current joint state is malformed: {exc}"
        ) from exc


def _controller_identity(config_dir: Path, controller_name: str, joints: tuple[str, ...]) -> ControllerIdentity:
    path = config_dir / "controllers.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        manager = data["controller_manager"]["ros__parameters"]
        plugin = manager[controller_name]["type"]
        raw = data[controller_name]["ros__parameters"]
        configured_joints = tuple(raw["joints"])
        interfaces = tuple(raw["command_interfaces"])
    except (KeyError, OSError, TypeError, yaml.YAMLError) as exc:
        raise ReadinessError(
            DiagnosticCode.READINESS_UNAVAILABLE,
            f"controller configuration unavailable: {exc}",
        ) from exc
    if (
        plugin != "joint_trajectory_controller/JointTrajectoryController"
        or configured_joints != joints
        or interfaces != ("position",)
    ):
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "controller identity mismatch")
    return ControllerIdentity(controller_name, configured_joints, interfaces)


def _planning_profile(config_dir: Path) -> PlanningProfile:
    path = config_dir / "moveit" / "joint_limits.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        velocity = float(data["default_velocity_scaling_factor"])
        acceleration = float(data["default_acceleration_scaling_factor"])
    except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise ReadinessError(
            DiagnosticCode.READINESS_UNAVAILABLE,
            f"planning profile unavailable: {exc}",
        ) from exc
    return PlanningProfile(
        pipeline_id="ompl",
        planner_id="",
        num_planning_attempts=1,
        allowed_planning_time_s=5.0,
        max_velocity_scaling_factor=velocity,
        max_acceleration_scaling_factor=acceleration,
    )


class RosReadinessAdapter:
    """Collect one fresh, hashed plan-only readiness snapshot from ROS/config."""

    def __init__(
        self,
        node: object,
        *,
        provenance_path: Path,
        max_age_ns: int = 500_000_000,
        timeout_s: float = 5.0,
    ) -> None:
        if isinstance(max_age_ns, bool) or not isinstance(max_age_ns, int) or max_age_ns <= 0:
            raise ValueError("max_age_ns must be a positive integer")
        if timeout_s <= 0:
            raise ValueError("readiness timeout must be positive")
        try:
            from ament_index_python.packages import get_package_share_directory
            from geometry_msgs.msg import TransformStamped
            from sensor_msgs.msg import JointState
            from tf2_ros import Buffer, TransformException
        except (ImportError, ModuleNotFoundError) as exc:
            raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, f"ROS readiness unavailable: {exc}") from exc
        self._node = node
        self._max_age_ns = max_age_ns
        self._timeout_s = timeout_s
        self._share = Path(get_package_share_directory("workbench_motion"))
        self._arm = load_arm_config(self._share / "config" / "arm.yaml")
        self._latest_joint_state: object | None = None
        self._latest_joint_state_observed_at_ns: int | None = None
        self._latest_joint_state_clock: tuple[int, int] | None = None
        self._latest_joint_state_publisher_gid: bytes | None = None
        self._tf_messages: list[tuple[str, object, tuple[int, int], bytes]] = []
        self._callback_error: ReadinessError | None = None
        self.last_error: ReadinessError | None = None
        self._last_readiness: ReadinessSnapshot | None = None
        self._last_clock_proof: dict[str, object] | None = None
        self._provenance_armed_at_ns: int | None = None
        self._tf_buffer = Buffer()
        self._load_provenance(
            provenance_path,
            joint_state_type=JointState,
            transform_type=TransformStamped,
        )
        self._subscription = None
        self._tf_subscription = None
        self._tf_static_subscription = None
        self._transform_exception = TransformException

    def _load_provenance(self, path: Path, *, joint_state_type: type, transform_type: type) -> None:
        payload = _wait_for_provenance_payload(path, self._timeout_s)
        self._provenance_armed_at_ns = payload["armed_at_ns"]
        joint = payload["joint_state"]
        message = joint_state_type()
        try:
            header = _require_closed_keys(joint["header"], {"sec", "nanosec"}, "joint header")
            message.header.stamp.sec = header["sec"]
            message.header.stamp.nanosec = header["nanosec"]
            message.name = joint["name"]
            message.position = joint["position"]
            joint_gid = bytes.fromhex(joint["publisher_gid"])
            joint_clock = (joint["source_timestamp_ns"], joint["received_timestamp_ns"])
        except (AttributeError, TypeError, ValueError) as exc:
            raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, f"joint provenance is malformed: {exc}") from exc
        self._latest_joint_state = message
        self._latest_joint_state_clock = joint_clock
        self._latest_joint_state_publisher_gid = joint_gid
        self._latest_joint_state_observed_at_ns = joint_clock[1]
        self._tf_messages = []
        for topic, key, is_static in (("/tf", "tf", False), ("/tf_static", "tf_static", True)):
            sample = payload[key]
            try:
                sample_gid = bytes.fromhex(sample["publisher_gid"])
                sample_clock = (sample["source_timestamp_ns"], sample["received_timestamp_ns"])
                transforms = sample["transforms"]
            except (KeyError, TypeError, ValueError) as exc:
                raise ReadinessError(
                    DiagnosticCode.READINESS_UNAVAILABLE, f"TF provenance is malformed: {exc}"
                ) from exc
            if not isinstance(transforms, list):
                raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "TF provenance transforms are malformed")
            for raw_transform in transforms:
                transform_data = _require_closed_keys(
                    raw_transform,
                    {"header", "child_frame_id", "translation", "rotation"},
                    "TF transform",
                )
                header = _require_closed_keys(transform_data["header"], {"sec", "nanosec", "frame_id"}, "TF header")
                transform = transform_type()
                try:
                    transform.header.stamp.sec = header["sec"]
                    transform.header.stamp.nanosec = header["nanosec"]
                    transform.header.frame_id = header["frame_id"]
                    transform.child_frame_id = transform_data["child_frame_id"]
                    translation = transform_data["translation"]
                    rotation = transform_data["rotation"]
                    if not isinstance(translation, list) or len(translation) != 3:
                        raise ValueError("translation length")
                    if not isinstance(rotation, list) or len(rotation) != 4:
                        raise ValueError("rotation length")
                    transform.transform.translation.x = translation[0]
                    transform.transform.translation.y = translation[1]
                    transform.transform.translation.z = translation[2]
                    transform.transform.rotation.x = rotation[0]
                    transform.transform.rotation.y = rotation[1]
                    transform.transform.rotation.z = rotation[2]
                    transform.transform.rotation.w = rotation[3]
                    if is_static:
                        self._tf_buffer.set_transform_static(transform, "c3a_rmw_sample_provenance")
                    else:
                        self._tf_buffer.set_transform(transform, "c3a_rmw_sample_provenance")
                except (AttributeError, TypeError, ValueError) as exc:
                    raise ReadinessError(
                        DiagnosticCode.READINESS_UNAVAILABLE, f"TF provenance transform is malformed: {exc}"
                    ) from exc
                self._tf_messages.append((topic, transform, sample_clock, sample_gid))

    def _component_hashes(self, robot_description: str) -> tuple[tuple[str, str], ...]:
        config = self._share / "config"
        sources = (
            ("arm.yaml", config / "arm.yaml"),
            ("workbench_arm.srdf", config / "moveit" / "workbench_arm.srdf"),
            ("kinematics.yaml", config / "moveit" / "kinematics.yaml"),
            ("ompl_planning.yaml", config / "moveit" / "ompl_planning.yaml"),
            ("moveit_joint_limits.yaml", config / "moveit" / "joint_limits.yaml"),
            ("controllers.yaml", config / "controllers.yaml"),
            ("trajectory_preflight.yaml", config / "trajectory_preflight.yaml"),
            ("joint_limits.hw_override.yaml", config / "joint_limits.hw_override.yaml"),
        )
        try:
            file_hashes = tuple((name, sha256_bytes(path.read_bytes())) for name, path in sources)
        except OSError as exc:
            raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, f"config hash input missing: {exc}") from exc
        return (("robot_description", sha256_bytes(robot_description.encode("utf-8"))), *file_hashes)

    def _robot_description(self) -> str:
        try:
            value = self._node.get_parameter("robot_description").value
        except (AttributeError, RuntimeError, TypeError) as exc:
            raise ReadinessError(
                DiagnosticCode.READINESS_UNAVAILABLE,
                f"expanded robot_description unavailable: {exc}",
            ) from exc
        if not isinstance(value, str) or not value:
            raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "expanded robot_description is empty")
        return value

    def _configuration_facts(self, robot_description: str | None = None) -> _ConfigurationFacts:
        config_dir = self._share / "config"
        if robot_description is None:
            robot_description = self._robot_description()
        packages = (
            "workbench_motion",
            "moveit_msgs",
            "moveit_core",
            "moveit_ros_planning",
            "moveit_ros_move_group",
            "moveit_planners_ompl",
            "moveit_kinematics",
            "trac_ik_kinematics_plugin",
            "joint_state_publisher",
            "robot_state_publisher",
            self._arm.vendor_description_pkg,
            "robotiq_description",
        )
        return _ConfigurationFacts(
            controller=_controller_identity(
                config_dir,
                self._arm.arm_trajectory_controller,
                self._arm.joints,
            ),
            planning_profile=_planning_profile(config_dir),
            preflight_context=build_preflight_context(),
            component_hashes=self._component_hashes(robot_description),
            package_versions=tuple((package, _package_version(package)) for package in packages),
        )

    def _build_snapshot(self) -> ReadinessSnapshot:
        if self._callback_error is not None:
            raise self._callback_error
        if (
            self._latest_joint_state is None
            or self._latest_joint_state_observed_at_ns is None
            or self._latest_joint_state_clock is None
            or self._latest_joint_state_publisher_gid is None
        ):
            raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "joint state unavailable")
        clock_domain_id, graph_clock_proof_sha256, proven_gids, graph_clock_proof = _prove_source_clock_domain(
            self._node,
            timeout_s=self._timeout_s,
            expected_publishers=_HARNESS_CLOCK_PUBLISHERS,
        )
        if not self._tf_messages:
            raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "TF samples are unavailable")
        message = self._latest_joint_state
        try:
            names = tuple(message.name)
            positions = tuple(message.position)
            if len(names) != len(positions) or len(names) != len(set(names)):
                raise ValueError("joint state names/positions mismatch")
            state = dict(zip(names, positions, strict=True))
            current = tuple((joint, float(state[joint])) for joint in self._arm.joints)
            joint_timestamp_ns = _stamp_ns(message.header.stamp)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ReadinessError(
                DiagnosticCode.READINESS_UNAVAILABLE,
                f"joint state incomplete: {exc}",
            ) from exc
        try:
            from rclpy.time import Time

            transform = self._tf_buffer.lookup_transform(
                self._arm.base_frame,
                self._arm.ik_tip_link,
                Time(),
            )
        except self._transform_exception as exc:
            raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, f"TF unavailable: {exc}") from exc
        transform_observed_at_ns = int(self._node.get_clock().now().nanoseconds)
        translation = transform.transform.translation
        rotation = transform.transform.rotation
        robot_description = self._robot_description()
        full_current = _model_ordered_joint_state(robot_description, state)
        configuration = self._configuration_facts(robot_description)
        checked_at_ns = int(self._node.get_clock().now().nanoseconds)
        transform_timestamp_ns = _stamp_ns(transform.header.stamp)
        tf_sample_clocks = tuple(
            (topic, _stamp_ns(observed_transform.header.stamp), sample_clock, sample_gids)
            for topic, observed_transform, sample_clock, sample_gids in self._tf_messages
        )
        clock_proof_sha256, clock_proof = _bind_sample_clock_proof(
            domain_id=clock_domain_id,
            graph_proof_sha256=graph_clock_proof_sha256,
            graph_proof=graph_clock_proof,
            checked_at_ns=checked_at_ns,
            max_age_ns=self._max_age_ns,
            joint_header_ns=joint_timestamp_ns,
            joint_clock=self._latest_joint_state_clock,
            joint_publisher_gid=self._latest_joint_state_publisher_gid,
            tf_samples=tf_sample_clocks,
            proven_gids=proven_gids,
            selected_transform_header_ns=transform_timestamp_ns,
            provenance_armed_at_ns=self._provenance_armed_at_ns,
        )
        if (
            checked_at_ns - joint_timestamp_ns > self._max_age_ns
            or checked_at_ns - transform_timestamp_ns > self._max_age_ns
            or checked_at_ns - self._latest_joint_state_observed_at_ns > self._max_age_ns
            or checked_at_ns - transform_observed_at_ns > self._max_age_ns
            or joint_timestamp_ns > checked_at_ns
            or transform_timestamp_ns > checked_at_ns
        ):
            raise ReadinessError(DiagnosticCode.READINESS_STALE, "joint-state or TF readiness is stale")
        candidate = ReadinessSnapshot(
            model=self._arm.model,
            planning_group=self._arm.planning_group,
            planning_frame=self._arm.base_frame,
            ik_tip_link=self._arm.ik_tip_link,
            joint_names=self._arm.joints,
            current_joint_positions=current,
            full_joint_positions=full_current,
            joint_state_timestamp_ns=joint_timestamp_ns,
            joint_state_observed_at_ns=self._latest_joint_state_observed_at_ns,
            transform=TransformSnapshot(
                parent_frame=self._arm.base_frame,
                child_frame=self._arm.ik_tip_link,
                translation=(translation.x, translation.y, translation.z),
                rotation=(rotation.x, rotation.y, rotation.z, rotation.w),
                timestamp_ns=transform_timestamp_ns,
            ),
            transform_observed_at_ns=transform_observed_at_ns,
            checked_at_ns=checked_at_ns,
            max_age_ns=self._max_age_ns,
            joint_state_timestamp_clock_id=clock_domain_id,
            transform_timestamp_clock_id=clock_domain_id,
            joint_state_observation_clock_id=clock_domain_id,
            transform_observation_clock_id=clock_domain_id,
            checked_at_clock_id=clock_domain_id,
            clock_proof_sha256=clock_proof_sha256,
            controller=configuration.controller,
            planning_profile=configuration.planning_profile,
            preflight_context=configuration.preflight_context,
            component_hashes=configuration.component_hashes,
            package_versions=configuration.package_versions,
            config_sha256="",
            readiness_sha256="",
        )
        snapshot = validate_readiness(seal_readiness(candidate))
        self._last_clock_proof = clock_proof
        return snapshot

    def snapshot(self) -> ReadinessSnapshot:
        import rclpy

        deadline = time.monotonic() + self._timeout_s
        self._node.get_logger().info(f"C3a readiness window seconds={self._timeout_s}")
        last_error: ReadinessError | None = None
        while time.monotonic() < deadline:
            rclpy.spin_once(self._node, timeout_sec=min(0.1, deadline - time.monotonic()))
            try:
                snapshot = self._build_snapshot()
                self._last_readiness = snapshot
                return snapshot
            except ReadinessError as exc:
                last_error = exc
                self.last_error = exc
        if last_error is not None:
            self._node.get_logger().error(f"C3a readiness deadline: {last_error}")
            raise last_error
        raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "readiness timeout")

    def configuration_sha256(self) -> str:
        reference = self._last_readiness
        if reference is None:
            raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "readiness snapshot is unavailable")
        configuration = self._configuration_facts()
        candidate = replace(
            reference,
            controller=configuration.controller,
            planning_profile=configuration.planning_profile,
            preflight_context=configuration.preflight_context,
            component_hashes=configuration.component_hashes,
            package_versions=configuration.package_versions,
            config_sha256="",
            readiness_sha256="",
        )
        return seal_readiness(candidate).config_sha256

    def acceptance_evidence(self) -> dict[str, object]:
        snapshot = self._last_readiness
        proof = self._last_clock_proof
        if snapshot is None or proof is None:
            raise ReadinessError(DiagnosticCode.READINESS_UNAVAILABLE, "acceptance evidence is unavailable")
        if sha256_bytes(canonical_json_bytes(proof)) != snapshot.clock_proof_sha256:
            raise ReadinessError(DiagnosticCode.CONTEXT_MISMATCH, "clock proof evidence hash mismatch")
        return {
            "clock_proof": json.loads(canonical_json_bytes(proof)),
            "component_hashes": dict(snapshot.component_hashes),
            "package_versions": dict(snapshot.package_versions),
        }
