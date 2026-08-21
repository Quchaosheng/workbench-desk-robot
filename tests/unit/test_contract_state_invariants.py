import pytest
from workbench_contracts import ActionResult, VerificationResult


def action_result(**updates) -> ActionResult:
    values = {
        "result_id": "result-1",
        "action_id": "action-1",
        "run_id": "run-1",
        "outcome": "completed",
        "dispatch_state": "sent",
        "device_state": "confirmed",
        "started_at": "1",
        "ended_at": "2",
    }
    return ActionResult(**(values | updates))


def verification_result(**updates) -> VerificationResult:
    values = {
        "verification_id": "verification-1",
        "run_id": "run-1",
        "task_id": "task-1",
        "claim": "goal satisfied",
        "status": "confirmed",
        "reason_code": "goal_satisfied",
        "completeness": 1.0,
        "evidence_refs": ["frame://1"],
        "recovery_hint": "none",
        "verified_at": "3",
    }
    return VerificationResult(**(values | updates))


@pytest.mark.parametrize(
    ("dispatch_state", "device_state"),
    [("send_failed", "rejected"), ("sent", "rejected"), ("not_sent", "unconfirmed")],
)
def test_completed_action_requires_confirmed_delivery(dispatch_state: str, device_state: str) -> None:
    with pytest.raises(ValueError, match="completed action"):
        action_result(dispatch_state=dispatch_state, device_state=device_state)

    assert action_result()
    assert action_result(outcome="timeout", dispatch_state="sent", device_state="unconfirmed")


@pytest.mark.parametrize(
    "updates",
    [
        {"reason_code": "target_not_observed"},
        {"completeness": 0.0},
        {"recovery_hint": "re_observe"},
        {"status": "refuted", "reason_code": "goal_satisfied", "recovery_hint": "retry_action"},
        {
            "status": "insufficient_evidence",
            "reason_code": "goal_satisfied",
            "recovery_hint": "re_observe",
        },
    ],
)
def test_verification_rejects_contradictory_status_semantics(updates: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        verification_result(**updates)

    assert verification_result()
    assert verification_result(reason_code=None, completeness=None)
    assert verification_result(
        status="refuted",
        reason_code="goal_not_satisfied",
        completeness=1.0,
        recovery_hint="retry_action",
    )
    assert verification_result(
        status="insufficient_evidence",
        reason_code="target_not_observed",
        completeness=0.5,
        recovery_hint="re_observe",
    )
