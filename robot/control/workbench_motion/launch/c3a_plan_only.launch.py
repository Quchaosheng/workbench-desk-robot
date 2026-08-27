"""Bounded C3a acceptance harness with MoveIt execution disabled."""

import os
import signal
from dataclasses import dataclass
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    OpaqueFunction,
    RegisterEventHandler,
    Shutdown,
    TimerAction,
)
from launch.event_handlers import OnProcessExit
from launch.events import matches_action
from launch.events.process import SignalProcess
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from workbench_motion.launch_utils import move_group_parameters, require_file, robot_description

_SHARE = Path(get_package_share_directory("workbench_motion"))
_CONFIG_DIR = _SHARE / "config"
_DEFAULT_ARM_XACRO = str(_CONFIG_DIR / "arm_on_workbench.urdf.xacro")


@dataclass(frozen=True, slots=True)
class _ArtifactPaths:
    evidence: Path
    staging: Path
    provenance: Path
    provenance_request: Path

    @classmethod
    def from_evidence(cls, evidence: Path) -> "_ArtifactPaths":
        return cls(
            evidence=evidence,
            staging=evidence.with_name(f".{evidence.name}.pending"),
            provenance=evidence.with_name(f"{evidence.name}.provenance.json"),
            provenance_request=evidence.with_name(f"{evidence.name}.provenance-request.json"),
        )

    def any_exists(self) -> bool:
        return any(path.exists() for path in (self.evidence, self.staging, self.provenance, self.provenance_request))

    def remove(self) -> None:
        for path in (self.staging, self.evidence, self.provenance, self.provenance_request):
            path.unlink(missing_ok=True)


@dataclass(slots=True)
class _HarnessState:
    probe_succeeded: bool = False
    provenance_succeeded: bool = False
    move_group_stop_requested: bool = False
    move_group_exited: bool = False
    support_stop_requested: bool = False
    rsp_exited: bool = False
    jsp_exited: bool = False
    harness_completed: bool = False
    harness_failing: bool = False


def _shutdown_after_probe(event, _context, state: _HarnessState, move_group, artifacts: _ArtifactPaths):
    if event.returncode != 0:
        state.harness_failing = True
        artifacts.remove()
        raise RuntimeError(f"C3a probe failed with return code {event.returncode}")
    state.probe_succeeded = True
    state.move_group_stop_requested = True
    return [
        TimerAction(
            period=1.0,
            actions=[
                EmitEvent(
                    event=SignalProcess(
                        signal_number=signal.SIGKILL,
                        process_matcher=matches_action(move_group),
                    )
                )
            ],
        )
    ]


def _record_provenance_exit(event, _context, state: _HarnessState, artifacts: _ArtifactPaths):
    if event.returncode != 0 or not artifacts.provenance.is_file():
        state.harness_failing = True
        artifacts.remove()
        raise RuntimeError(f"C3a provenance collector failed with return code {event.returncode}")
    state.provenance_succeeded = True
    artifacts.provenance_request.unlink(missing_ok=True)
    return _complete_if_ready(state, artifacts)


def _publish_evidence(artifacts: _ArtifactPaths) -> None:
    if not artifacts.staging.is_file():
        raise RuntimeError("C3a staged evidence is missing after successful probe")
    try:
        os.link(artifacts.staging, artifacts.evidence)
    except FileExistsError as exc:
        raise RuntimeError(f"refusing to overwrite existing C3a evidence: {artifacts.evidence}") from exc
    artifacts.staging.unlink()


def _complete_if_ready(state: _HarnessState, artifacts: _ArtifactPaths):
    if state.harness_completed or state.harness_failing:
        return []
    if not all(
        (
            state.provenance_succeeded,
            state.probe_succeeded,
            state.move_group_exited,
            state.rsp_exited,
            state.jsp_exited,
        )
    ):
        return []
    _publish_evidence(artifacts)
    artifacts.provenance.unlink(missing_ok=True)
    artifacts.provenance_request.unlink(missing_ok=True)
    state.harness_completed = True
    return [Shutdown(reason="C3a harness teardown completed")]


def _move_group_exit(event, _context, state: _HarnessState, artifacts: _ArtifactPaths, rsp, jsp):
    if state.harness_failing:
        artifacts.remove()
        return []
    if state.move_group_stop_requested and event.returncode in {0, -signal.SIGKILL}:
        state.move_group_exited = True
        state.support_stop_requested = True
        return [
            EmitEvent(event=SignalProcess(signal_number=signal.SIGINT, process_matcher=matches_action(rsp))),
            EmitEvent(event=SignalProcess(signal_number=signal.SIGINT, process_matcher=matches_action(jsp))),
        ]
    state.harness_failing = True
    artifacts.remove()
    raise RuntimeError(f"MoveGroup failed during C3a harness shutdown: {event.returncode}")


def _support_process_exit(name, event, _context, state: _HarnessState, artifacts: _ArtifactPaths):
    if state.harness_failing:
        artifacts.remove()
        return []
    if not state.support_stop_requested or event.returncode != 0:
        state.harness_failing = True
        artifacts.remove()
        raise RuntimeError(f"C3a support process {name} exited unexpectedly: {event.returncode}")
    setattr(state, f"{name}_exited", True)
    return _complete_if_ready(state, artifacts)


def _watchdog_expired(_context, state: _HarnessState, artifacts: _ArtifactPaths):
    if state.harness_completed:
        return []
    state.harness_failing = True
    artifacts.remove()
    raise RuntimeError("C3a harness deadline expired before probe completion")


def _setup(context, *_args, **_kwargs):
    arm_xacro = Path(LaunchConfiguration("arm_xacro").perform(context))
    evidence_path = LaunchConfiguration("evidence_path").perform(context)
    final_evidence = Path(evidence_path)
    artifacts = _ArtifactPaths.from_evidence(final_evidence)
    if artifacts.any_exists():
        raise RuntimeError("C3a evidence, staging, provenance, or request destination already exists")
    state = _HarnessState()
    require_file(arm_xacro, "arm xacro")
    description = robot_description(arm_xacro)
    moveit_params = move_group_parameters(_SHARE, description, use_sim_time=False)
    move_group = Node(
        package="moveit_ros_move_group",
        executable="move_group",
        name="move_group",
        output="screen",
        parameters=[
            *moveit_params,
            {
                "allow_trajectory_execution": False,
                "disable_capabilities": "move_group/MoveGroupExecuteTrajectoryAction",
            },
        ],
    )
    rsp = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="screen",
        parameters=[description, {"use_sim_time": False}],
    )
    jsp = Node(
        package="joint_state_publisher",
        executable="joint_state_publisher",
        output="screen",
        parameters=[
            {
                "use_sim_time": False,
                "zeros.shoulder_pan_joint": 0.0,
                "zeros.shoulder_lift_joint": -1.0472,
                "zeros.elbow_joint": 1.0472,
                "zeros.wrist_1_joint": -1.5708,
                "zeros.wrist_2_joint": -1.5708,
                "zeros.wrist_3_joint": 0.0,
            }
        ],
    )
    probe = Node(
        package="workbench_motion",
        executable="c3a_plan_probe",
        output="screen",
        parameters=[
            description,
            {
                "evidence_path": str(artifacts.staging),
                "provenance_path": str(artifacts.provenance),
                "provenance_request_path": str(artifacts.provenance_request),
                "timeout_s": 10.0,
                "max_age_ns": 500_000_000,
                "use_sim_time": False,
            },
        ],
    )
    provenance = Node(
        package="workbench_motion_provenance",
        executable="c3a_sample_provenance",
        output="screen",
        parameters=[
            {
                "output_path": str(artifacts.provenance),
                "request_path": str(artifacts.provenance_request),
                "timeout_s": 10.0,
                "use_sim_time": False,
            }
        ],
    )
    provenance_guard = RegisterEventHandler(
        OnProcessExit(
            target_action=provenance,
            on_exit=lambda event, launch_context: _record_provenance_exit(
                event,
                launch_context,
                state,
                artifacts,
            ),
        )
    )
    shutdown = RegisterEventHandler(
        OnProcessExit(
            target_action=probe,
            on_exit=lambda event, launch_context: _shutdown_after_probe(
                event,
                launch_context,
                state,
                move_group,
                artifacts,
            ),
        )
    )
    move_group_guard = RegisterEventHandler(
        OnProcessExit(
            target_action=move_group,
            on_exit=lambda event, launch_context: _move_group_exit(
                event,
                launch_context,
                state,
                artifacts,
                rsp,
                jsp,
            ),
        )
    )
    rsp_guard = RegisterEventHandler(
        OnProcessExit(
            target_action=rsp,
            on_exit=lambda event, launch_context: _support_process_exit("rsp", event, launch_context, state, artifacts),
        )
    )
    jsp_guard = RegisterEventHandler(
        OnProcessExit(
            target_action=jsp,
            on_exit=lambda event, launch_context: _support_process_exit("jsp", event, launch_context, state, artifacts),
        )
    )
    watchdog = TimerAction(
        period=30.0,
        actions=[
            OpaqueFunction(
                function=lambda launch_context: _watchdog_expired(
                    launch_context,
                    state,
                    artifacts,
                )
            )
        ],
    )
    return [
        provenance_guard,
        shutdown,
        move_group_guard,
        rsp_guard,
        jsp_guard,
        rsp,
        jsp,
        move_group,
        provenance,
        probe,
        watchdog,
    ]


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument("arm_xacro", default_value=_DEFAULT_ARM_XACRO),
            DeclareLaunchArgument("evidence_path"),
            OpaqueFunction(function=_setup),
        ]
    )
