"""Fail-closed sequential orchestration for already-typed semantic actions.

The controller owns dispatch ordering and execution-state evidence only.  It
does not cancel an active Motion goal, create contract results, write world
state, verify task completion, or infer physical execution.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from workbench_contracts import ActionOutcome, ActionResult, ActionType, SemanticAction, TaskGraph, TaskStep

from .policy_validator import PolicyDecision, PolicyReport, PolicyValidator


class ExecutionState(StrEnum):
    """Deterministic controller states for one dispatch record."""

    PENDING = "pending"
    DISPATCHED = "dispatched"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    STOPPED = "stopped"


class ExecutionReasonCode(StrEnum):
    """Stable report and record reasons without completion claims."""

    SEQUENCE_SUCCEEDED = "sequence_succeeded"
    INVALID_INPUT = "invalid_input"
    INVALID_GRAPH = "invalid_graph"
    POLICY_REJECTED = "policy_rejected"
    DUPLICATE_ACTION = "duplicate_action"
    ACTION_FAILED = "action_failed"
    ACTION_TIMED_OUT = "action_timed_out"
    ACTION_CANCELLED = "action_cancelled"
    ACTION_STOPPED = "action_stopped"
    ADAPTER_TIMEOUT = "adapter_timeout"
    ADAPTER_EXCEPTION = "adapter_exception"
    INVALID_ADAPTER_RESULT = "invalid_adapter_result"
    STOP_DISPATCHED = "stop_dispatched"


class StopRequestStatus(StrEnum):
    """Synchronous acknowledgement for queuing a dispatch-boundary STOP."""

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


@runtime_checkable
class ActionAdapter(Protocol):
    """Typed adapter port owned by the caller's execution boundary."""

    def dispatch(self, action: SemanticAction) -> ActionResult:
        """Dispatch exactly one typed semantic action."""


@dataclass(frozen=True)
class StepExecutionRecord:
    """Immutable orchestration evidence for one action."""

    step_id: str
    action_id: str
    transitions: tuple[ExecutionState, ...]
    result: ActionResult | None = None
    reason_code: ExecutionReasonCode | None = None
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionReport:
    """Immutable controller report; not verification or WorldState evidence."""

    task_id: str | None
    terminal_state: ExecutionState
    reason_code: ExecutionReasonCode
    records: tuple[StepExecutionRecord, ...]
    policy_report: PolicyReport | None = None
    details: tuple[str, ...] = ()


@dataclass
class _RecordBuilder:
    step_id: str
    action_id: str
    transitions: list[ExecutionState] = field(default_factory=lambda: [ExecutionState.PENDING])
    result: ActionResult | None = None
    reason_code: ExecutionReasonCode | None = None
    details: tuple[str, ...] = ()

    def freeze(self) -> StepExecutionRecord:
        return StepExecutionRecord(
            step_id=self.step_id,
            action_id=self.action_id,
            transitions=tuple(self.transitions),
            result=self.result,
            reason_code=self.reason_code,
            details=self.details,
        )


_RESULT_STATES: dict[ActionOutcome, tuple[ExecutionState, ExecutionReasonCode | None]] = {
    ActionOutcome.COMPLETED: (ExecutionState.SUCCEEDED, None),
    ActionOutcome.FAILED: (ExecutionState.FAILED, ExecutionReasonCode.ACTION_FAILED),
    ActionOutcome.TIMEOUT: (ExecutionState.TIMED_OUT, ExecutionReasonCode.ACTION_TIMED_OUT),
    ActionOutcome.CANCELED: (ExecutionState.CANCELLED, ExecutionReasonCode.ACTION_CANCELLED),
    ActionOutcome.SAFE_STOP: (ExecutionState.STOPPED, ExecutionReasonCode.ACTION_STOPPED),
}


class ExecutionController:
    """Preflight, revalidate, and sequentially dispatch one typed TaskGraph.

    Duplicate suppression and STOP queuing are deliberately in-memory and
    scoped to this running controller instance.  STOP is examined only between
    adapter calls; interrupting an already-active call belongs to Motion.
    """

    def __init__(self, *, policy_validator: PolicyValidator, adapter: ActionAdapter) -> None:
        if not isinstance(policy_validator, PolicyValidator):
            raise TypeError("policy_validator must be a PolicyValidator")
        if not isinstance(adapter, ActionAdapter):
            raise TypeError("adapter must implement ActionAdapter")
        self._policy_validator = policy_validator
        self._adapter = adapter
        self._dispatched_action_ids: set[str] = set()
        self._accepted_stop_action_ids: set[str] = set()
        self._pending_stop: SemanticAction | None = None

    def request_stop(self, action: SemanticAction) -> StopRequestStatus:
        """Queue one typed STOP for the next controller dispatch boundary."""

        if not isinstance(action, SemanticAction):
            return StopRequestStatus.REJECTED
        action_snapshot, snapshot_errors = _snapshot_semantic_action(action)
        if snapshot_errors or action_snapshot is None or action_snapshot.action_type is not ActionType.STOP:
            return StopRequestStatus.REJECTED
        if (
            action_snapshot.action_id in self._accepted_stop_action_ids
            or action_snapshot.action_id in self._dispatched_action_ids
        ):
            return StopRequestStatus.DUPLICATE
        if self._pending_stop is not None:
            return StopRequestStatus.REJECTED
        self._accepted_stop_action_ids.add(action_snapshot.action_id)
        self._pending_stop = action_snapshot
        return StopRequestStatus.ACCEPTED

    def execute(
        self,
        graph: TaskGraph,
        *,
        confirmed_action_ids: frozenset[str] = frozenset(),
    ) -> ExecutionReport:
        """Execute a graph sequentially after full-graph fail-closed preflight."""

        if not isinstance(graph, TaskGraph):
            return ExecutionReport(
                task_id=None,
                terminal_state=ExecutionState.FAILED,
                reason_code=ExecutionReasonCode.INVALID_INPUT,
                records=(),
                details=(f"expected TaskGraph, got {type(graph).__name__}",),
            )

        graph_snapshot, snapshot_errors = _snapshot_task_graph(graph)
        if graph_snapshot is None:
            task_id = graph.task_id if isinstance(graph.task_id, str) else None
            return ExecutionReport(
                task_id=task_id,
                terminal_state=ExecutionState.FAILED,
                reason_code=ExecutionReasonCode.INVALID_GRAPH,
                records=(),
                details=snapshot_errors,
            )

        records = [_RecordBuilder(step.step_id, step.action.action_id) for step in graph_snapshot.steps]
        confirmation_snapshot = _snapshot_confirmed_action_ids(confirmed_action_ids)
        if confirmation_snapshot is None:
            return self._report(
                graph_snapshot,
                ExecutionState.FAILED,
                ExecutionReasonCode.INVALID_INPUT,
                records,
                details=("confirmed_action_ids must be a set or frozenset of non-blank strings",),
            )

        graph_payload = graph_snapshot.model_dump(mode="json")
        structure_errors = _graph_structure_errors(graph_snapshot)
        if structure_errors:
            return self._report(
                graph_snapshot,
                ExecutionState.FAILED,
                ExecutionReasonCode.INVALID_GRAPH,
                records,
                details=structure_errors,
            )

        repeated_ids = tuple(
            step.action.action_id
            for step in graph_snapshot.steps
            if step.action.action_id in self._dispatched_action_ids
        )
        if repeated_ids:
            return self._report(
                graph_snapshot,
                ExecutionState.FAILED,
                ExecutionReasonCode.DUPLICATE_ACTION,
                records,
                details=tuple(f"action_id already dispatched: {action_id}" for action_id in repeated_ids),
            )

        preflight, policy_errors = self._check_policy(
            graph_snapshot,
            confirmation_snapshot,
        )
        if policy_errors or preflight is None:
            return self._report(
                graph_snapshot,
                ExecutionState.FAILED,
                ExecutionReasonCode.POLICY_REJECTED,
                records,
                policy_report=preflight,
                details=policy_errors,
            )
        if not preflight.is_valid:
            return self._report(
                graph_snapshot,
                ExecutionState.FAILED,
                ExecutionReasonCode.POLICY_REJECTED,
                records,
                policy_report=preflight,
            )

        for index, step in enumerate(graph_snapshot.steps):
            if self._pending_stop is not None:
                changed = self._live_graph_failure(
                    graph,
                    graph_snapshot,
                    graph_payload,
                    records,
                    record_index=index,
                    policy_report=preflight,
                )
                if changed is not None:
                    return changed
                return self._dispatch_stop(
                    graph_snapshot,
                    records,
                    preflight,
                    confirmation_snapshot,
                )

            step_graph = self._single_step_graph(graph_snapshot, step)
            dispatch_policy, policy_errors = self._check_policy(
                step_graph,
                confirmation_snapshot,
            )
            if policy_errors or dispatch_policy is None or not dispatch_policy.is_valid:
                record = records[index]
                record.transitions.append(ExecutionState.FAILED)
                record.reason_code = ExecutionReasonCode.POLICY_REJECTED
                record.details = policy_errors
                return self._report(
                    graph_snapshot,
                    ExecutionState.FAILED,
                    ExecutionReasonCode.POLICY_REJECTED,
                    records,
                    policy_report=dispatch_policy,
                    details=policy_errors,
                )

            changed = self._live_graph_failure(
                graph,
                graph_snapshot,
                graph_payload,
                records,
                record_index=index,
                policy_report=preflight,
            )
            if changed is not None:
                return changed

            terminal = self._dispatch_action(step.action, records[index])
            if terminal is not None:
                state, reason = terminal
                return self._report(
                    graph_snapshot,
                    state,
                    reason,
                    records,
                    policy_report=preflight,
                )

        changed = self._live_graph_failure(
            graph,
            graph_snapshot,
            graph_payload,
            records,
            record_index=None,
            policy_report=preflight,
        )
        if changed is not None:
            return changed

        if self._pending_stop is not None:
            return self._dispatch_stop(
                graph_snapshot,
                records,
                preflight,
                confirmation_snapshot,
            )

        return self._report(
            graph_snapshot,
            ExecutionState.SUCCEEDED,
            ExecutionReasonCode.SEQUENCE_SUCCEEDED,
            records,
            policy_report=preflight,
        )

    def _dispatch_stop(
        self,
        graph: TaskGraph,
        records: list[_RecordBuilder],
        preflight: PolicyReport,
        confirmed_action_ids: frozenset[str],
    ) -> ExecutionReport:
        queued_action = self._pending_stop
        if queued_action is None:  # pragma: no cover - caller guards the boundary
            raise RuntimeError("STOP dispatch requested without a pending STOP")

        queued_action_id = queued_action.action_id if isinstance(queued_action.action_id, str) else "<invalid-stop>"
        stop_record = _RecordBuilder(
            step_id=queued_action_id,
            action_id=queued_action_id,
        )
        records.append(stop_record)

        action, snapshot_errors = _snapshot_semantic_action(queued_action)
        if snapshot_errors or action is None or action.action_type is not ActionType.STOP:
            self._pending_stop = None
            stop_record.transitions.append(ExecutionState.FAILED)
            stop_record.reason_code = ExecutionReasonCode.INVALID_INPUT
            stop_record.details = ("pending STOP snapshot is invalid",)
            return self._report(
                graph,
                ExecutionState.FAILED,
                ExecutionReasonCode.INVALID_INPUT,
                records,
                policy_report=preflight,
                details=stop_record.details,
            )

        stop_graph = TaskGraph(
            task_id=graph.task_id,
            goal=graph.goal,
            steps=[TaskStep(step_id=action.action_id, action=action)],
            planner=graph.planner,
            model_route=graph.model_route,
        )
        stop_policy, policy_errors = self._check_policy(
            stop_graph,
            confirmed_action_ids,
        )
        if policy_errors or stop_policy is None or not stop_policy.is_valid:
            stop_record.transitions.append(ExecutionState.FAILED)
            stop_record.reason_code = ExecutionReasonCode.POLICY_REJECTED
            stop_record.details = policy_errors
            return self._report(
                graph,
                ExecutionState.FAILED,
                ExecutionReasonCode.POLICY_REJECTED,
                records,
                policy_report=stop_policy,
                details=policy_errors,
            )

        self._pending_stop = None
        terminal = self._dispatch_action(action, stop_record)
        if terminal is not None:
            state, reason = terminal
            return self._report(
                graph,
                state,
                reason,
                records,
                policy_report=preflight,
            )
        return self._report(
            graph,
            ExecutionState.STOPPED,
            ExecutionReasonCode.STOP_DISPATCHED,
            records,
            policy_report=preflight,
        )

    def _dispatch_action(
        self,
        action: SemanticAction,
        record: _RecordBuilder,
    ) -> tuple[ExecutionState, ExecutionReasonCode] | None:
        action_snapshot, snapshot_errors = _snapshot_semantic_action(action)
        if (
            snapshot_errors or action_snapshot is None or action_snapshot.action_id != record.action_id
        ):  # pragma: no cover - callers provide validated snapshots
            record.transitions.append(ExecutionState.FAILED)
            record.reason_code = ExecutionReasonCode.INVALID_INPUT
            record.details = snapshot_errors or (f"expected action_id {record.action_id}",)
            return ExecutionState.FAILED, ExecutionReasonCode.INVALID_INPUT

        expected_action_id = action_snapshot.action_id
        if expected_action_id in self._dispatched_action_ids:
            record.transitions.append(ExecutionState.FAILED)
            record.reason_code = ExecutionReasonCode.DUPLICATE_ACTION
            record.details = (f"action_id already dispatched: {expected_action_id}",)
            return ExecutionState.FAILED, ExecutionReasonCode.DUPLICATE_ACTION

        record.transitions.append(ExecutionState.DISPATCHED)
        self._dispatched_action_ids.add(expected_action_id)
        try:
            result = self._adapter.dispatch(action_snapshot)
        except TimeoutError:
            record.transitions.append(ExecutionState.TIMED_OUT)
            record.reason_code = ExecutionReasonCode.ADAPTER_TIMEOUT
            record.details = ("TimeoutError",)
            return ExecutionState.TIMED_OUT, ExecutionReasonCode.ADAPTER_TIMEOUT
        except Exception as error:  # noqa: BLE001 - adapter failures become typed fail-closed records
            record.transitions.append(ExecutionState.FAILED)
            record.reason_code = ExecutionReasonCode.ADAPTER_EXCEPTION
            record.details = (type(error).__name__,)
            return ExecutionState.FAILED, ExecutionReasonCode.ADAPTER_EXCEPTION

        if not isinstance(result, ActionResult):
            record.transitions.append(ExecutionState.FAILED)
            record.reason_code = ExecutionReasonCode.INVALID_ADAPTER_RESULT
            record.details = (f"expected ActionResult, got {type(result).__name__}",)
            return ExecutionState.FAILED, ExecutionReasonCode.INVALID_ADAPTER_RESULT

        result_snapshot, result_errors = _snapshot_action_result(result)
        if result_snapshot is None:
            record.transitions.append(ExecutionState.FAILED)
            record.reason_code = ExecutionReasonCode.INVALID_ADAPTER_RESULT
            record.details = result_errors
            return ExecutionState.FAILED, ExecutionReasonCode.INVALID_ADAPTER_RESULT

        if result_snapshot.action_id != expected_action_id:
            record.transitions.append(ExecutionState.FAILED)
            record.reason_code = ExecutionReasonCode.INVALID_ADAPTER_RESULT
            record.details = (f"expected action_id {expected_action_id}, got {result_snapshot.action_id}",)
            return ExecutionState.FAILED, ExecutionReasonCode.INVALID_ADAPTER_RESULT

        state, reason = _RESULT_STATES[result_snapshot.outcome]
        record.transitions.append(state)
        record.result = result_snapshot
        record.reason_code = reason
        if reason is None:
            return None
        return state, reason

    def _check_policy(
        self,
        graph: TaskGraph,
        confirmed_action_ids: frozenset[str],
    ) -> tuple[PolicyReport | None, tuple[str, ...]]:
        policy_graph, snapshot_errors = _snapshot_task_graph(graph)
        if policy_graph is None:  # pragma: no cover - callers provide validated snapshots
            return None, snapshot_errors
        policy_payload = policy_graph.model_dump(mode="json")

        try:
            report = self._policy_validator.check(
                policy_graph,
                confirmed_action_ids=confirmed_action_ids,
            )
        except Exception:  # noqa: BLE001 - injected validation must fail closed
            return None, ("PolicyValidator.check raised",)

        if not isinstance(report, PolicyReport):
            return None, (f"PolicyValidator.check returned {type(report).__name__}",)

        checked_graph, checked_errors = _snapshot_task_graph(policy_graph)
        if checked_errors or checked_graph is None or checked_graph.model_dump(mode="json") != policy_payload:
            return report, ("PolicyValidator mutated policy input",)

        expected_decisions = tuple((step.step_id, step.action.action_id) for step in checked_graph.steps)
        if (
            not isinstance(report.decisions, tuple)
            or any(not isinstance(decision, PolicyDecision) for decision in report.decisions)
            or tuple((decision.step_id, decision.action_id) for decision in report.decisions) != expected_decisions
        ):
            return report, ("PolicyValidator.check decisions do not exactly match policy input",)
        return report, ()

    def _live_graph_failure(
        self,
        live_graph: TaskGraph,
        graph_snapshot: TaskGraph,
        graph_payload: dict[str, object],
        records: list[_RecordBuilder],
        *,
        record_index: int | None,
        policy_report: PolicyReport,
    ) -> ExecutionReport | None:
        change = _task_graph_change(
            live_graph,
            graph_snapshot,
            graph_payload,
            self._dispatched_action_ids,
        )
        if change is None:
            return None

        reason, details = change
        if record_index is not None:
            record = records[record_index]
            if record.transitions == [ExecutionState.PENDING]:
                record.transitions.append(ExecutionState.FAILED)
                record.reason_code = reason
                record.details = details
        return self._report(
            graph_snapshot,
            ExecutionState.FAILED,
            reason,
            records,
            policy_report=policy_report,
            details=details,
        )

    @staticmethod
    def _single_step_graph(graph: TaskGraph, step: TaskStep) -> TaskGraph:
        return TaskGraph(
            task_id=graph.task_id,
            goal=graph.goal,
            steps=[step],
            planner=graph.planner,
            model_route=graph.model_route,
        )

    @staticmethod
    def _report(
        graph: TaskGraph,
        terminal_state: ExecutionState,
        reason_code: ExecutionReasonCode,
        records: list[_RecordBuilder],
        *,
        policy_report: PolicyReport | None = None,
        details: tuple[str, ...] = (),
    ) -> ExecutionReport:
        return ExecutionReport(
            task_id=graph.task_id,
            terminal_state=terminal_state,
            reason_code=reason_code,
            records=tuple(record.freeze() for record in records),
            policy_report=policy_report,
            details=details,
        )


def _snapshot_confirmed_action_ids(value: object) -> frozenset[str] | None:
    if not isinstance(value, set | frozenset):
        return None
    try:
        items = tuple(value)
    except Exception:  # noqa: BLE001 - malformed caller input must fail closed
        return None
    if any(not isinstance(action_id, str) or not action_id.strip() for action_id in items):
        return None
    return frozenset(items)


def _snapshot_task_graph(
    graph: TaskGraph,
) -> tuple[TaskGraph | None, tuple[str, ...]]:
    try:
        payload = deepcopy(graph.model_dump(mode="python", warnings="error"))
        return TaskGraph.model_validate(payload, strict=True), ()
    except Exception as error:  # noqa: BLE001 - mutable model input must fail closed
        return None, (f"TaskGraph snapshot validation failed: {type(error).__name__}",)


def _snapshot_semantic_action(
    action: SemanticAction,
) -> tuple[SemanticAction | None, tuple[str, ...]]:
    try:
        payload = deepcopy(action.model_dump(mode="python", warnings="error"))
        return SemanticAction.model_validate(payload, strict=True), ()
    except Exception as error:  # noqa: BLE001 - mutable model input must fail closed
        return None, (f"SemanticAction snapshot validation failed: {type(error).__name__}",)


def _snapshot_action_result(
    result: ActionResult,
) -> tuple[ActionResult | None, tuple[str, ...]]:
    try:
        payload = deepcopy(result.model_dump(mode="python", warnings="error"))
        return ActionResult.model_validate(payload, strict=True), ()
    except Exception as error:  # noqa: BLE001 - adapter output must fail closed
        return None, (f"ActionResult snapshot validation failed: {type(error).__name__}",)


def _task_graph_change(
    live_graph: TaskGraph,
    graph_snapshot: TaskGraph,
    graph_payload: dict[str, object],
    dispatched_action_ids: set[str],
) -> tuple[ExecutionReasonCode, tuple[str, ...]] | None:
    live_snapshot, _snapshot_errors = _snapshot_task_graph(live_graph)
    if live_snapshot is None:
        return (
            ExecutionReasonCode.INVALID_GRAPH,
            ("TaskGraph mutated during execution",),
        )
    if live_snapshot.model_dump(mode="json") == graph_payload:
        return None

    for index, live_step in enumerate(live_snapshot.steps):
        if index >= len(graph_snapshot.steps):
            break
        expected_action_id = graph_snapshot.steps[index].action.action_id
        live_action_id = live_step.action.action_id
        if live_action_id != expected_action_id and live_action_id in dispatched_action_ids:
            details = (f"action_id already dispatched: {live_action_id}",)
            return ExecutionReasonCode.DUPLICATE_ACTION, details

    return (
        ExecutionReasonCode.INVALID_GRAPH,
        ("TaskGraph mutated during execution",),
    )


def _graph_structure_errors(graph: TaskGraph) -> tuple[str, ...]:
    errors: list[str] = []
    step_ids = [step.step_id for step in graph.steps]
    action_ids = [step.action.action_id for step in graph.steps]

    for duplicate in _duplicates(step_ids):
        errors.append(f"duplicate step_id: {duplicate}")
    for duplicate in _duplicates(action_ids):
        errors.append(f"duplicate action_id: {duplicate}")

    first_index = {step_id: index for index, step_id in enumerate(step_ids)}
    dependencies: dict[str, tuple[str, ...]] = {}
    for index, step in enumerate(graph.steps):
        dependencies[step.step_id] = tuple(step.depends_on)
        for dependency in step.depends_on:
            if dependency not in first_index:
                errors.append(f"{step.step_id} has missing dependency: {dependency}")
            elif dependency == step.step_id:
                errors.append(f"{step.step_id} depends on itself")
            elif first_index[dependency] > index:
                errors.append(f"{step.step_id} has forward dependency: {dependency}")

    if _has_dependency_cycle(dependencies):
        errors.append("cyclic dependency detected")
    return tuple(errors)


def _duplicates(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return tuple(duplicates)


def _has_dependency_cycle(dependencies: dict[str, tuple[str, ...]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> bool:
        if step_id in visiting:
            return True
        if step_id in visited:
            return False
        visiting.add(step_id)
        for dependency in dependencies.get(step_id, ()):
            if dependency in dependencies and visit(dependency):
                return True
        visiting.remove(step_id)
        visited.add(step_id)
        return False

    return any(visit(step_id) for step_id in dependencies)


__all__ = [
    "ActionAdapter",
    "ExecutionController",
    "ExecutionReasonCode",
    "ExecutionReport",
    "ExecutionState",
    "StepExecutionRecord",
    "StopRequestStatus",
]
