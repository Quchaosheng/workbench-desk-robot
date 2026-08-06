import json
from pathlib import Path
from typing import Any

from .expression import ALLOWED_TRANSITIONS, ExpressionState, derive_expression

STATUS_LABELS = {
    "confirmed": "已确认",
    "insufficient_evidence": "证据不足",
    "refuted": "未满足",
    "running": "执行中",
}

STEP_LABELS = {
    "action_request": "执行语义动作",
    "action_result": "检查动作结果",
    "observation": "观察工作区",
    "task_accepted": "接收任务",
    "task_graph": "生成任务计划",
    "task_terminal": "任务结束",
    "verification": "验证任务结果",
}


class DashboardReadModel:
    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)

    def _paths(self) -> list[Path]:
        return sorted(self.data_dir.glob("*.jsonl"))

    def ready(self) -> bool:
        return self.data_dir.is_dir() and bool(self._paths())

    def list_events(self, run_id: str) -> list[dict[str, Any]]:
        for path in self._paths():
            events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if events and events[0].get("run_id") == run_id:
                return sorted(events, key=lambda event: event.get("sequence_no", -1))
        raise KeyError(run_id)

    def list_runs(self) -> list[dict[str, Any]]:
        return [self.summarize(self.list_events(path.stem)) for path in self._paths()]

    def summarize(self, events: list[dict[str, Any]], replay_index: int | None = None) -> dict[str, Any]:
        if not events:
            raise ValueError("cannot summarize an empty run")
        visible = events if replay_index is None else events[: replay_index + 1]
        accepted = next((event for event in events if event.get("event_type") == "task_accepted"), events[0])
        verifications = [event for event in visible if event.get("event_type") == "verification"]
        final_verification = verifications[-1] if verifications else None
        status = final_verification.get("payload", {}).get("status", "running") if final_verification else "running"
        missing_evidence = (
            final_verification.get("payload", {}).get("missing_evidence", []) if final_verification else []
        )
        current_event = visible[-1] if visible else None
        recovery_count = sum(
            event.get("event_type") == "verification" and event.get("payload", {}).get("status") == "refuted"
            for event in visible
        )
        evidence = []
        for event in visible:
            for reference in event.get("evidence_refs", []):
                if reference not in evidence:
                    evidence.append(reference)
        return {
            "run_id": events[0]["run_id"],
            "task_id": accepted.get("payload", {}).get("task_id", "unknown"),
            "goal": accepted.get("payload", {}).get("goal", "Place the red block in the tray"),
            "mode": accepted.get("payload", {}).get("mode", "scripted"),
            "status": status,
            "status_label": STATUS_LABELS[status],
            "expression": derive_expression(visible).value,
            "current_step": STEP_LABELS.get(current_event.get("event_type"), "等待任务")
            if current_event
            else "等待任务",
            "progress": round(len(visible) / len(events) * 100) if events else 0,
            "event_count": len(events),
            "visible_event_count": len(visible),
            "updated_at": visible[-1].get("occurred_at") if visible else None,
            "missing_evidence": missing_evidence,
            "evidence_refs": evidence,
            "recovery_count": recovery_count,
            "safety": {"hardware_estop": "not_connected", "software_control": "read_only"},
        }

    def expression_contract(self) -> dict[str, Any]:
        return {
            "states": [state.value for state in ExpressionState],
            "transitions": {
                state.value: sorted(next_state.value for next_state in transitions)
                for state, transitions in ALLOWED_TRANSITIONS.items()
            },
        }
