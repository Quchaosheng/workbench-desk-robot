import pytest
from workbench_contracts import (
    ActionOutcome,
    ActionResult,
    DeviceState,
    DispatchState,
    ReasonCode,
    RecoveryHint,
    VerificationResult,
    VerificationStatus,
)


def action_result(**updates) -> ActionResult:
    values = {
        "result_id": "result-1",
        "action_id": "action-1",
        "run_id": "run-1",
        "outcome": ActionOutcome.COMPLETED,
        "dispatch_state": DispatchState.SENT,
        "device_state": DeviceState.CONFIRMED,
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
        "status": VerificationStatus.CONFIRMED,
        "reason_code": ReasonCode.GOAL_SATISFIED,
        "completeness": 1.0,
        "evidence_refs": ["frame://1"],
        "recovery_hint": RecoveryHint.NONE,
        "verified_at": "3",
    }
    return VerificationResult(**(values | updates))


@pytest.mark.parametrize(
    ("dispatch_state", "device_state"),
    [
        (DispatchState.SEND_FAILED, DeviceState.REJECTED),
        (DispatchState.SENT, DeviceState.REJECTED),
        (DispatchState.NOT_SENT, DeviceState.UNCONFIRMED),
    ],
)
def test_completed_action_requires_confirmed_delivery(
    dispatch_state: DispatchState,
    device_state: DeviceState,
) -> None:
    with pytest.raises(ValueError, match="completed action"):
        action_result(dispatch_state=dispatch_state, device_state=device_state)

    assert action_result()
    assert action_result(
        outcome=ActionOutcome.TIMEOUT,
        dispatch_state=DispatchState.SENT,
        device_state=DeviceState.UNCONFIRMED,
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"reason_code": ReasonCode.TARGET_NOT_OBSERVED},
        {"completeness": 0.0},
        {"recovery_hint": RecoveryHint.RE_OBSERVE},
        {
            "status": VerificationStatus.REFUTED,
            "reason_code": ReasonCode.GOAL_SATISFIED,
            "recovery_hint": RecoveryHint.RETRY_ACTION,
        },
        {
            "status": VerificationStatus.INSUFFICIENT_EVIDENCE,
            "reason_code": ReasonCode.GOAL_SATISFIED,
            "recovery_hint": RecoveryHint.RE_OBSERVE,
        },
    ],
)
def test_verification_rejects_contradictory_status_semantics(updates: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        verification_result(**updates)

    assert verification_result()
    assert verification_result(reason_code=None, completeness=None)
    assert verification_result(
        status=VerificationStatus.REFUTED,
        reason_code=ReasonCode.GOAL_NOT_SATISFIED,
        completeness=1.0,
        recovery_hint=RecoveryHint.RETRY_ACTION,
    )
    assert verification_result(
        status=VerificationStatus.INSUFFICIENT_EVIDENCE,
        reason_code=ReasonCode.TARGET_NOT_OBSERVED,
        completeness=0.5,
        recovery_hint=RecoveryHint.RE_OBSERVE,
    )
