"""Structural acceptance tests for the bounded C3a plan-only harness."""

from __future__ import annotations

import ast
import importlib.util
import json
import signal
import sys
import types
from pathlib import Path

import pytest
from workbench_motion.c3a_plan_probe import _CONTROLLED_GOAL, _atomic_create, _request_fresh_provenance

PACKAGE = Path(__file__).parents[1]

_LAUNCH_PATH = PACKAGE / "launch" / "c3a_plan_only.launch.py"


class _FakeAction:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


def harness_state(**changes):
    state = {
        "probe_succeeded": False,
        "provenance_succeeded": False,
        "move_group_stop_requested": False,
        "move_group_exited": False,
        "support_stop_requested": False,
        "rsp_exited": False,
        "jsp_exited": False,
        "harness_completed": False,
        "harness_failing": False,
    }
    state.update(changes)
    return types.SimpleNamespace(**state)


def artifact_paths(launch_module, tmp_path):
    return launch_module._ArtifactPaths.from_evidence(tmp_path / "evidence.json")


@pytest.fixture
def launch_module(monkeypatch):
    fake_ament = types.ModuleType("ament_index_python.packages")
    fake_ament.get_package_share_directory = lambda _name: str(PACKAGE)
    fake_launch = types.ModuleType("launch")
    fake_launch.LaunchDescription = _FakeAction
    fake_actions = types.ModuleType("launch.actions")
    for name in (
        "DeclareLaunchArgument",
        "EmitEvent",
        "OpaqueFunction",
        "RegisterEventHandler",
        "Shutdown",
        "TimerAction",
    ):
        action_type = type(name, (_FakeAction,), {})
        setattr(fake_launch, name, action_type)
        setattr(fake_actions, name, action_type)
    fake_handlers = types.ModuleType("launch.event_handlers")
    fake_handlers.OnProcessExit = type("OnProcessExit", (_FakeAction,), {})
    fake_launch_events = types.ModuleType("launch.events")
    fake_launch_events.matches_action = lambda action: action
    fake_events = types.ModuleType("launch.events.process")
    fake_events.SignalProcess = type("SignalProcess", (_FakeAction,), {})
    fake_substitutions = types.ModuleType("launch.substitutions")
    fake_substitutions.LaunchConfiguration = type("LaunchConfiguration", (), {})
    fake_launch_ros = types.ModuleType("launch_ros.actions")
    fake_launch_ros.Node = type("Node", (_FakeAction,), {})
    fake_utils = types.ModuleType("workbench_motion.launch_utils")
    fake_utils.move_group_parameters = lambda *args: []
    fake_utils.require_file = lambda *args: None
    fake_utils.robot_description = lambda *args: {}
    fake_modules = {
        "ament_index_python": types.ModuleType("ament_index_python"),
        "ament_index_python.packages": fake_ament,
        "launch": fake_launch,
        "launch.actions": fake_actions,
        "launch.event_handlers": fake_handlers,
        "launch.events": fake_launch_events,
        "launch.events.process": fake_events,
        "launch.substitutions": fake_substitutions,
        "launch_ros": types.ModuleType("launch_ros"),
        "launch_ros.actions": fake_launch_ros,
        "workbench_motion.launch_utils": fake_utils,
    }
    for name, module in fake_modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("c3a_plan_only_launch", _LAUNCH_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parsed(relative: str) -> ast.AST:
    return ast.parse((PACKAGE / relative).read_text(encoding="utf-8"))


def launch_arguments(tree: ast.AST) -> set[str]:
    return {
        call.args[0].value
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "DeclareLaunchArgument"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    }


def false_parameter_values(tree: ast.AST, name: str) -> list[ast.expr]:
    values = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if isinstance(key, ast.Constant) and key.value == name:
                values.append(value)
    return values


def constant_parameter_values(tree: ast.AST, name: str) -> list[object]:
    return [
        value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values, strict=True)
        if isinstance(key, ast.Constant) and key.value == name and isinstance(value, ast.Constant)
    ]


def test_c3a_launch_has_no_execution_override_and_forces_move_group_false():
    tree = parsed("launch/c3a_plan_only.launch.py")

    assert launch_arguments(tree) == {"arm_xacro", "evidence_path"}
    values = false_parameter_values(tree, "allow_trajectory_execution")
    assert len(values) == 1
    assert isinstance(values[0], ast.Constant)
    assert values[0].value is False
    assert constant_parameter_values(tree, "disable_capabilities") == ["move_group/MoveGroupExecuteTrajectoryAction"]


def test_general_move_group_launch_is_also_execution_disabled():
    tree = parsed("launch/move_group.launch.py")

    assert "allow_trajectory_execution" not in launch_arguments(tree)
    values = false_parameter_values(tree, "allow_trajectory_execution")
    assert len(values) == 1
    assert isinstance(values[0], ast.Constant)
    assert values[0].value is False
    assert constant_parameter_values(tree, "disable_capabilities") == ["move_group/MoveGroupExecuteTrajectoryAction"]


def test_harness_probe_exit_is_bounded_and_failure_is_raised():
    tree = parsed("launch/c3a_plan_only.launch.py")
    assert any(
        isinstance(call.func, ast.Name) and call.func.id == "OnProcessExit"
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
    )
    assert any(isinstance(node, ast.Raise) for node in ast.walk(tree))
    assert any(
        isinstance(call.func, ast.Name) and call.func.id == "Shutdown"
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
    )
    assert any(
        isinstance(call.func, ast.Name) and call.func.id == "TimerAction"
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
    )
    source = (PACKAGE / "launch" / "c3a_plan_only.launch.py").read_text(encoding="utf-8")
    assert "state.probe_succeeded" in source
    assert "unlink(missing_ok=True)" in source
    assert "MoveGroup failed during C3a harness shutdown" in source


def test_probe_entry_point_and_direct_runtime_dependency_are_declared():
    setup = (PACKAGE / "setup.py").read_text(encoding="utf-8")
    package_xml = (PACKAGE / "package.xml").read_text(encoding="utf-8")

    assert "c3a_plan_probe = workbench_motion.c3a_plan_probe:main" in setup
    assert "<exec_depend>shape_msgs</exec_depend>" in package_xml


def test_provenance_collector_binds_actual_rmw_writer_and_has_no_execution_transport():
    source = (PACKAGE.parent / "workbench_motion_provenance" / "src" / "c3a_sample_provenance.cpp").read_text(
        encoding="utf-8"
    )

    assert "info.get_rmw_message_info()" in source
    assert "rmw_info.publisher_gid.data" in source
    assert "rmw_info.source_timestamp" in source
    assert "rmw_info.received_timestamp" in source
    assert "sample writer GID does not match graph endpoint" in source
    assert "ExecuteTrajectory" not in source
    assert "FollowJointTrajectory" not in source
    assert "request_path_" in source
    assert "joint_state_.reset()" in source
    assert "dynamic_tf_.reset()" in source
    assert "unlink(request_path_.c_str())" in source
    assert "armed_at_ns_" in source
    assert "received_timestamp_ns <= *armed_at_ns_" in source


def test_controlled_probe_goal_is_pose_only_and_top_down():
    assert _CONTROLLED_GOAL.frame_id == "world"
    assert _CONTROLLED_GOAL.tolerance_profile == "standard"
    assert _CONTROLLED_GOAL.pose.qx == pytest.approx(0.8253356149096783)
    assert _CONTROLLED_GOAL.pose.qy == pytest.approx(-0.5646424733950354)
    assert _CONTROLLED_GOAL.pose.qz == 0.0
    assert _CONTROLLED_GOAL.pose.qw == 0.0
    assert not hasattr(_CONTROLLED_GOAL, "joint_names")
    assert not hasattr(_CONTROLLED_GOAL, "velocity")


def test_probe_evidence_is_create_only_and_strict_json(tmp_path):
    output = tmp_path / "evidence.json"
    payload = {
        "schema_version": "c3a-plan-only-1",
        "execution_goal_count": 0,
        "gazebo": "NOT_EXECUTED",
        "physical": "NOT_EXECUTED",
    }

    _atomic_create(output, payload)

    assert json.loads(output.read_text(encoding="utf-8")) == payload
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        _atomic_create(output, payload)


def test_probe_evidence_requires_absolute_path():
    with pytest.raises(ValueError, match="must be absolute"):
        _atomic_create(Path("relative.json"), {})


def test_probe_requests_fresh_provenance_with_create_only_marker(tmp_path):
    request = tmp_path / "provenance-request.json"

    _request_fresh_provenance(request)

    assert json.loads(request.read_text(encoding="utf-8")) == {"schema_version": "c3a-provenance-request-1"}
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        _request_fresh_provenance(request)


def test_probe_exit_only_schedules_shutdown_after_success(tmp_path, launch_module):
    state = harness_state()
    artifacts = artifact_paths(launch_module, tmp_path)
    event = type("Event", (), {"returncode": 0})()

    actions = launch_module._shutdown_after_probe(event, None, state, object(), artifacts)

    assert state.probe_succeeded is True
    assert state.move_group_stop_requested is True
    assert len(actions) == 1
    assert type(actions[0]).__name__ == "TimerAction"


def test_probe_failure_removes_request_and_all_partial_artifacts(tmp_path, launch_module):
    state = harness_state()
    artifacts = artifact_paths(launch_module, tmp_path)
    for path in (artifacts.staging, artifacts.provenance, artifacts.provenance_request):
        path.write_text("partial", encoding="utf-8")

    with pytest.raises(RuntimeError, match="probe failed"):
        launch_module._shutdown_after_probe(type("Event", (), {"returncode": 1})(), None, state, object(), artifacts)

    assert state.harness_failing is True
    assert not artifacts.any_exists()


def test_successful_provenance_exit_is_recorded(tmp_path, launch_module):
    artifacts = artifact_paths(launch_module, tmp_path)
    artifacts.provenance.write_text("{}", encoding="utf-8")
    artifacts.provenance_request.write_text("{}", encoding="utf-8")
    state = harness_state()
    actions = launch_module._record_provenance_exit(
        type("Event", (), {"returncode": 0})(),
        None,
        state,
        artifacts,
    )

    assert actions == []
    assert state.provenance_succeeded is True
    assert not artifacts.provenance_request.exists()


def test_provenance_failure_removes_all_artifacts(tmp_path, launch_module):
    artifacts = artifact_paths(launch_module, tmp_path)
    for path in (artifacts.evidence, artifacts.staging, artifacts.provenance, artifacts.provenance_request):
        path.write_text("partial", encoding="utf-8")

    with pytest.raises(RuntimeError, match="provenance collector failed"):
        launch_module._record_provenance_exit(
            type("Event", (), {"returncode": 1})(),
            None,
            state := harness_state(),
            artifacts,
        )

    assert not artifacts.any_exists()
    assert state.harness_failing is True


def test_move_group_failure_removes_evidence_after_probe_success(tmp_path, launch_module):
    artifacts = artifact_paths(launch_module, tmp_path)
    artifacts.staging.write_text("{}", encoding="utf-8")
    artifacts.provenance_request.write_text("{}", encoding="utf-8")
    state = harness_state(probe_succeeded=True)
    event = type("Event", (), {"returncode": -11})()

    with pytest.raises(RuntimeError, match="shutdown"):
        launch_module._move_group_exit(event, None, state, artifacts, object(), object())

    assert not artifacts.any_exists()


def test_expected_bounded_move_group_termination_waits_for_support_processes(tmp_path, launch_module):
    artifacts = artifact_paths(launch_module, tmp_path)
    artifacts.staging.write_text("{}", encoding="utf-8")
    state = harness_state(probe_succeeded=True, move_group_stop_requested=True)
    event = type("Event", (), {"returncode": -signal.SIGKILL})()

    actions = launch_module._move_group_exit(event, None, state, artifacts, object(), object())

    assert not artifacts.evidence.exists()
    assert artifacts.staging.exists()
    assert state.move_group_exited is True
    assert state.support_stop_requested is True
    assert len(actions) == 2
    assert all(type(action).__name__ == "EmitEvent" for action in actions)


def test_evidence_is_published_only_after_both_support_processes_exit(tmp_path, launch_module):
    artifacts = artifact_paths(launch_module, tmp_path)
    artifacts.staging.write_text("{}", encoding="utf-8")
    state = harness_state(
        provenance_succeeded=True,
        probe_succeeded=True,
        move_group_stop_requested=True,
        move_group_exited=True,
        support_stop_requested=True,
    )
    event = type("Event", (), {"returncode": 0})()

    assert launch_module._support_process_exit("rsp", event, None, state, artifacts) == []
    assert not artifacts.evidence.exists()
    actions = launch_module._support_process_exit("jsp", event, None, state, artifacts)

    assert artifacts.evidence.exists()
    assert not artifacts.staging.exists()
    assert not artifacts.provenance.exists()
    assert not artifacts.provenance_request.exists()
    assert state.harness_completed is True
    assert len(actions) == 1
    assert type(actions[0]).__name__ == "Shutdown"


def test_evidence_waits_when_provenance_process_exits_last(tmp_path, launch_module):
    artifacts = artifact_paths(launch_module, tmp_path)
    artifacts.staging.write_text("{}", encoding="utf-8")
    artifacts.provenance.write_text("{}", encoding="utf-8")
    state = harness_state(
        probe_succeeded=True,
        move_group_stop_requested=True,
        move_group_exited=True,
        support_stop_requested=True,
    )
    event = type("Event", (), {"returncode": 0})()

    assert launch_module._support_process_exit("jsp", event, None, state, artifacts) == []
    assert launch_module._support_process_exit("rsp", event, None, state, artifacts) == []
    assert not artifacts.evidence.exists()

    actions = launch_module._record_provenance_exit(event, None, state, artifacts)

    assert artifacts.evidence.exists()
    assert state.harness_completed is True
    assert len(actions) == 1
    assert type(actions[0]).__name__ == "Shutdown"


@pytest.mark.parametrize("handler", ["move_group", "rsp", "jsp"])
def test_failure_state_suppresses_exit_cascade_and_pass_artifact(tmp_path, launch_module, handler):
    artifacts = artifact_paths(launch_module, tmp_path)
    for path in (artifacts.staging, artifacts.provenance, artifacts.provenance_request):
        path.write_text("{}", encoding="utf-8")
    state = harness_state(harness_failing=True)
    event = type("Event", (), {"returncode": 0})()

    if handler == "move_group":
        actions = launch_module._move_group_exit(event, None, state, artifacts, object(), object())
    else:
        actions = launch_module._support_process_exit(handler, event, None, state, artifacts)

    assert actions == []
    assert not artifacts.any_exists()


def test_bounded_termination_refuses_to_overwrite_existing_evidence(tmp_path, launch_module):
    artifacts = artifact_paths(launch_module, tmp_path)
    artifacts.evidence.write_text("old", encoding="utf-8")
    artifacts.staging.write_text("new", encoding="utf-8")

    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        launch_module._publish_evidence(artifacts)

    assert artifacts.evidence.read_text(encoding="utf-8") == "old"


def test_harness_watchdog_removes_staging_and_fails_closed(tmp_path, launch_module):
    artifacts = artifact_paths(launch_module, tmp_path)
    artifacts.provenance.write_text("sample", encoding="utf-8")
    artifacts.staging.write_text("partial", encoding="utf-8")
    artifacts.provenance_request.write_text("request", encoding="utf-8")
    state = harness_state()

    with pytest.raises(RuntimeError, match="deadline expired"):
        launch_module._watchdog_expired(None, state, artifacts)

    assert not artifacts.any_exists()


def test_harness_watchdog_is_inert_after_complete_teardown(launch_module):
    state = harness_state(harness_completed=True)
    artifacts = launch_module._ArtifactPaths.from_evidence(Path("/unused"))

    assert launch_module._watchdog_expired(None, state, artifacts) == []
