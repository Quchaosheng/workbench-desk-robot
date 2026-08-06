from enum import StrEnum
from typing import Any


class ExpressionState(StrEnum):
    IDLE = "idle"
    THINKING = "thinking"
    UNCERTAIN = "uncertain"
    PLEASED = "pleased"


ALLOWED_TRANSITIONS = {
    ExpressionState.IDLE: {ExpressionState.THINKING},
    ExpressionState.THINKING: {ExpressionState.IDLE, ExpressionState.PLEASED, ExpressionState.UNCERTAIN},
    ExpressionState.UNCERTAIN: {ExpressionState.IDLE, ExpressionState.THINKING},
    ExpressionState.PLEASED: {ExpressionState.IDLE, ExpressionState.THINKING},
}


class ExpressionMachine:
    def __init__(self) -> None:
        self.state = ExpressionState.IDLE

    def transition(self, next_state: ExpressionState) -> ExpressionState:
        if next_state == self.state:
            return self.state
        if next_state not in ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(f"invalid expression transition: {self.state.value} -> {next_state.value}")
        self.state = next_state
        return self.state


def derive_expression(events: list[dict[str, Any]]) -> ExpressionState:
    """Derive expression from facts; it never decides whether the task succeeded."""
    if not events:
        return ExpressionState.IDLE
    latest_verification = next(
        (event for event in reversed(events) if event.get("event_type") == "verification"),
        None,
    )
    if latest_verification:
        status = latest_verification.get("payload", {}).get("status")
        if status == "confirmed":
            return ExpressionState.PLEASED
        if status in {"refuted", "insufficient_evidence"}:
            return ExpressionState.UNCERTAIN
    if any(event.get("event_type") == "task_accepted" for event in events):
        return ExpressionState.THINKING
    return ExpressionState.IDLE
