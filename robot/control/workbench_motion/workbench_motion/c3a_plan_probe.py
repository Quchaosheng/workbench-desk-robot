"""One-shot C3a plan-only probe that writes bounded machine evidence."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from workbench_motion.c3a_bridge import C3aPlanOnlyBridge
from workbench_motion.c3a_ros_adapter import (
    MoveGroupPlanningAdapter,
    RclpyMoveGroupTransport,
    RosReadinessAdapter,
)
from workbench_motion.c3a_types import PlanStatus, Pose, PosePlanGoal

_CONTROLLED_GOAL = PosePlanGoal(
    frame_id="world",
    pose=Pose(
        x=0.28,
        y=0.18,
        z=1.0,
        qx=0.8253356149096783,
        qy=-0.5646424733950354,
        qz=0.0,
        qw=0.0,
    ),
    tolerance_profile="standard",
)


def _atomic_create(path: Path, payload: dict[str, object]) -> None:
    if not path.is_absolute():
        raise ValueError("evidence_path must be absolute")
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _execution_is_disabled(node: object, timeout_s: float) -> bool:
    import rclpy
    from rclpy.parameter_client import AsyncParameterClient

    client = AsyncParameterClient(node, "/move_group")
    if not client.wait_for_services(timeout_sec=timeout_s):
        return False
    future = client.get_parameters(["allow_trajectory_execution", "disable_capabilities"])
    rclpy.spin_until_future_complete(node, future, timeout_sec=timeout_s)
    if not future.done():
        return False
    try:
        result = future.result()
        values = result.values
        if len(values) != 2:
            return False
        disabled = set(values[1].string_value.split())
        return (
            values[0].type == 1
            and values[0].bool_value is False
            and values[1].type == 4
            and "move_group/MoveGroupExecuteTrajectoryAction" in disabled
        )
    except (AttributeError, RuntimeError, TypeError):
        return False


def _request_fresh_provenance(path: Path) -> None:
    _atomic_create(path, {"schema_version": "c3a-provenance-request-1"})


def run_probe(
    node: object,
    evidence_path: Path,
    *,
    provenance_path: Path,
    provenance_request_path: Path,
    timeout_s: float,
    max_age_ns: int,
) -> int:
    if not _execution_is_disabled(node, timeout_s):
        node.get_logger().error("move_group allow_trajectory_execution is not proven false")
        return 2
    _request_fresh_provenance(provenance_request_path)
    readiness = RosReadinessAdapter(
        node,
        provenance_path=provenance_path,
        max_age_ns=max_age_ns,
        timeout_s=timeout_s,
    )
    planning = MoveGroupPlanningAdapter(
        RclpyMoveGroupTransport(node),
        timeout_s=timeout_s,
    )
    module = C3aPlanOnlyBridge(planning, readiness)
    result = module.plan(_CONTROLLED_GOAL)
    if result.status is not PlanStatus.PLANNED or result.accepted_trajectory is None:
        readiness_detail = None if readiness.last_error is None else str(readiness.last_error)
        node.get_logger().error(
            "C3a plan failed: "
            f"status={result.status.value} code={result.diagnostic_code.value} "
            f"moveit_error_code={result.moveit_error_code} "
            f"preflight_reason_code={result.preflight_reason_code} "
            f"readiness_detail={readiness_detail}"
        )
        return 1
    try:
        controller_snapshot = module.materialize(result.accepted_trajectory)
        readiness_evidence = readiness.acceptance_evidence()
        _atomic_create(
            evidence_path,
            {
                "schema_version": "c3a-plan-only-1",
                "status": result.status.value,
                "diagnostic_code": result.diagnostic_code.value,
                "planning_request_sha256": result.planning_request_sha256,
                "trajectory_sha256": controller_snapshot.trajectory_sha256,
                "effective_limits_sha256": controller_snapshot.effective_limits_sha256,
                "context_sha256": controller_snapshot.context_sha256,
                "config_sha256": controller_snapshot.config_sha256,
                "readiness_sha256": result.readiness_sha256,
                "clock_proof_sha256": result.clock_proof_sha256,
                **readiness_evidence,
                "controller_name": controller_snapshot.controller_name,
                "execution_goal_count": 0,
                "allow_trajectory_execution": False,
                "execute_trajectory_capability": "DISABLED",
                "execution_enabled": False,
                "move_group_shutdown_policy": "BOUNDED_SIGKILL_AFTER_PLAN",
                "gazebo": "NOT_EXECUTED",
                "physical": "NOT_EXECUTED",
            },
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        node.get_logger().error(f"C3a evidence failed closed: {type(exc).__name__}: {exc}")
        return 2
    node.get_logger().info(f"C3a plan-only evidence written to {evidence_path}")
    return 0


def main(args: list[str] | None = None) -> None:
    import rclpy
    from rclpy.executors import ExternalShutdownException

    rclpy.init(args=args)
    node = rclpy.create_node(
        "c3a_plan_probe",
        automatically_declare_parameters_from_overrides=True,
    )
    try:
        evidence_path = Path(node.get_parameter("evidence_path").value)
        provenance_path = Path(node.get_parameter("provenance_path").value)
        provenance_request_path = Path(node.get_parameter("provenance_request_path").value)
        timeout_s = float(node.get_parameter("timeout_s").value)
        max_age_ns = int(node.get_parameter("max_age_ns").value)
        code = run_probe(
            node,
            evidence_path,
            provenance_path=provenance_path,
            provenance_request_path=provenance_request_path,
            timeout_s=timeout_s,
            max_age_ns=max_age_ns,
        )
    except (AttributeError, ExternalShutdownException, OSError, RuntimeError, TypeError, ValueError) as exc:
        node.get_logger().error(f"C3a probe unavailable: {type(exc).__name__}: {exc}")
        code = 2
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    raise SystemExit(code)


if __name__ == "__main__":
    main(sys.argv)
