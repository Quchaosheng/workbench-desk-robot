import uuid

from workbench_contracts import (
    ReasonCode,
    RecoveryHint,
    VerificationResult,
    VerificationStatus,
)

from .reducer import WorldState


def verify_object_in_tray(state: WorldState, task_id: str, object_id: str, tray_id: str) -> VerificationResult:
    """Decide whether object_id is inside tray_id.

    Three outcomes, not two. If the object was never observed we cannot say the
    goal failed — we can only say we have no evidence either way, which is what
    INSUFFICIENT_EVIDENCE means. Collapsing that into False would report a
    failure the world never showed us.
    """
    expected_location = f"in:{tray_id}"
    actual_location = state.entity_locations.get(object_id)

    if actual_location is None:
        status = VerificationStatus.INSUFFICIENT_EVIDENCE
        reason_code = ReasonCode.TARGET_NOT_OBSERVED
        recovery_hint = RecoveryHint.RE_OBSERVE
        claim = f"{object_id} inside {tray_id}: never observed"
    elif actual_location == expected_location:
        status = VerificationStatus.CONFIRMED
        reason_code = ReasonCode.GOAL_SATISFIED
        recovery_hint = RecoveryHint.NONE
        claim = f"{object_id} inside {tray_id}"
    else:
        status = VerificationStatus.REFUTED
        reason_code = ReasonCode.GOAL_NOT_SATISFIED
        recovery_hint = RecoveryHint.RETRY_ACTION
        claim = f"{object_id} inside {tray_id}: found at {actual_location}"

    # A conclusion with no evidence is not a conclusion. The schema requires at
    # least one ref, so record why the chain is empty rather than emitting [].
    evidence_refs = state.evidence_refs or ["no-events-applied"]

    return VerificationResult(
        verification_id=f"ver-{uuid.uuid4().hex[:12]}",
        run_id=state.run_id,
        task_id=task_id,
        claim=claim,
        status=status,
        reason_code=reason_code,
        evidence_refs=evidence_refs,
        recovery_hint=recovery_hint,
        verified_at="1970-01-01T00:00:00Z",
        rule_version="tray-membership-v1",
    )
