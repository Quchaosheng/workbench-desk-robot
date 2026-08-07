import uuid

from workbench_contracts import ReasonCode, RecoveryHint, VerificationResult, VerificationStatus

from .reducer import WorldState

NO_EVIDENCE_REF = "system://world-state/no-evidence"


def _unique_evidence(state: WorldState) -> list[str]:
    evidence = list(state.evidence_refs)
    for references in state.entity_evidence_refs.values():
        evidence.extend(references)
    return list(dict.fromkeys(evidence))


def _missing_entity_evidence(state: WorldState, entity_ids: set[str]) -> list[str]:
    return sorted(entity_id for entity_id in entity_ids if not state.entity_evidence_refs.get(entity_id))


def _required_entity_set(entity_ids: list[str], label: str) -> set[str]:
    if not entity_ids or any(not isinstance(entity_id, str) or not entity_id.strip() for entity_id in entity_ids):
        raise ValueError(f"{label} requires non-empty entity IDs")
    if len(entity_ids) != len(set(entity_ids)):
        raise ValueError(f"{label} requires unique entity IDs")
    return set(entity_ids)


def _validate_confidence_threshold(value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0.0 <= value <= 1.0:
        raise ValueError("confidence_threshold must be between 0 and 1")


def _result(
    state: WorldState,
    task_id: str,
    claim: str,
    status: VerificationStatus,
    reason_code: ReasonCode,
    recovery_hint: RecoveryHint,
    rule_version: str,
) -> VerificationResult:
    return VerificationResult(
        verification_id=f"ver-{uuid.uuid4().hex[:12]}",
        run_id=state.run_id,
        task_id=task_id,
        claim=claim,
        status=status,
        reason_code=reason_code,
        evidence_refs=_unique_evidence(state) or [NO_EVIDENCE_REF],
        recovery_hint=recovery_hint,
        verified_at="1970-01-01T00:00:00Z",
        rule_version=rule_version,
    )


def verify_object_in_tray(state: WorldState, task_id: str, object_id: str, tray_id: str) -> VerificationResult:
    if not isinstance(object_id, str) or not object_id.strip() or not isinstance(tray_id, str) or not tray_id.strip():
        raise ValueError("object_id and tray_id must be non-empty")
    expected_location = f"in:{tray_id}"
    actual_location = state.entity_locations.get(object_id)
    evidence = _unique_evidence(state)
    if actual_location is None:
        status = VerificationStatus.INSUFFICIENT_EVIDENCE
        reason_code = ReasonCode.TARGET_NOT_OBSERVED
        recovery_hint = RecoveryHint.RE_OBSERVE
        claim = f"{object_id} inside {tray_id}: never observed"
    elif actual_location == expected_location and not evidence:
        status = VerificationStatus.INSUFFICIENT_EVIDENCE
        reason_code = ReasonCode.EVIDENCE_MISSING
        recovery_hint = RecoveryHint.RE_OBSERVE
        claim = f"{object_id} inside {tray_id}: relation has no evidence"
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
    return _result(state, task_id, claim, status, reason_code, recovery_hint, "tray-membership-v1")


def verify_kit_contents(
    state: WorldState,
    task_id: str,
    required_object_ids: list[str],
    tray_id: str = "kit_tray",
    confidence_threshold: float = 0.8,
) -> VerificationResult:
    required = _required_entity_set(required_object_ids, "kitting")
    if not isinstance(tray_id, str) or not tray_id.strip():
        raise ValueError("tray_id must be non-empty")
    _validate_confidence_threshold(confidence_threshold)
    expected_location = f"in:{tray_id}"
    unobserved = sorted(object_id for object_id in required if object_id not in state.entity_locations)
    misplaced = sorted(
        object_id
        for object_id in required
        if object_id in state.entity_locations and state.entity_locations[object_id] != expected_location
    )
    extras = sorted(
        object_id
        for object_id, location in state.entity_locations.items()
        if location == expected_location and object_id not in required
    )
    low_confidence = sorted(
        object_id for object_id in required if state.entity_confidence.get(object_id, 0.0) < confidence_threshold
    )
    missing_evidence = _missing_entity_evidence(state, required)
    claim = (
        f"kit in {tray_id}: unobserved={unobserved}; misplaced={misplaced}; extras={extras}; "
        f"low_confidence={low_confidence}; missing_evidence={missing_evidence}"
    )
    if unobserved:
        outcome = (VerificationStatus.INSUFFICIENT_EVIDENCE, ReasonCode.TARGET_NOT_OBSERVED, RecoveryHint.RE_OBSERVE)
    elif low_confidence:
        outcome = (
            VerificationStatus.INSUFFICIENT_EVIDENCE,
            ReasonCode.CONFIDENCE_BELOW_THRESHOLD,
            RecoveryHint.RE_OBSERVE,
        )
    elif missing_evidence:
        outcome = (VerificationStatus.INSUFFICIENT_EVIDENCE, ReasonCode.EVIDENCE_MISSING, RecoveryHint.RE_OBSERVE)
    elif misplaced or extras:
        outcome = (VerificationStatus.REFUTED, ReasonCode.GOAL_NOT_SATISFIED, RecoveryHint.RETRY_ACTION)
    else:
        outcome = (VerificationStatus.CONFIRMED, ReasonCode.GOAL_SATISFIED, RecoveryHint.NONE)
    return _result(state, task_id, claim, *outcome, "kit-contents-v1")


def verify_inspection_evidence(
    state: WorldState,
    task_id: str,
    required_entity_ids: list[str],
    confidence_threshold: float = 0.8,
) -> VerificationResult:
    required = _required_entity_set(required_entity_ids, "inspection")
    _validate_confidence_threshold(confidence_threshold)
    unobserved = sorted(entity_id for entity_id in required if entity_id not in state.entity_locations)
    low_confidence = sorted(
        entity_id for entity_id in required if state.entity_confidence.get(entity_id, 0.0) < confidence_threshold
    )
    missing_evidence = _missing_entity_evidence(state, required)
    claim = (
        f"inspection: unobserved={unobserved}; low_confidence={low_confidence}; " f"missing_evidence={missing_evidence}"
    )
    if unobserved:
        outcome = (VerificationStatus.INSUFFICIENT_EVIDENCE, ReasonCode.TARGET_NOT_OBSERVED, RecoveryHint.RE_OBSERVE)
    elif low_confidence:
        outcome = (
            VerificationStatus.INSUFFICIENT_EVIDENCE,
            ReasonCode.CONFIDENCE_BELOW_THRESHOLD,
            RecoveryHint.RE_OBSERVE,
        )
    elif missing_evidence:
        outcome = (VerificationStatus.INSUFFICIENT_EVIDENCE, ReasonCode.EVIDENCE_MISSING, RecoveryHint.RE_OBSERVE)
    else:
        outcome = (VerificationStatus.CONFIRMED, ReasonCode.GOAL_SATISFIED, RecoveryHint.NONE)
    return _result(state, task_id, claim, *outcome, "inspection-evidence-v1")


def verify_workspace_clearance(state: WorldState, task_id: str) -> VerificationResult:
    expected = {"blue_cylinder": "in:staging_bin", "red_block": "in:tray"}
    unobserved = sorted(entity_id for entity_id in expected if entity_id not in state.entity_locations)
    unmet = sorted(
        f"{entity_id}->{location}"
        for entity_id, location in expected.items()
        if entity_id in state.entity_locations and state.entity_locations[entity_id] != location
    )
    missing_evidence = _missing_entity_evidence(state, set(expected))
    claim = f"workspace clearance: unobserved={unobserved}; unmet={unmet}; missing_evidence={missing_evidence}"
    if unobserved:
        outcome = (VerificationStatus.INSUFFICIENT_EVIDENCE, ReasonCode.TARGET_NOT_OBSERVED, RecoveryHint.RE_OBSERVE)
    elif missing_evidence:
        outcome = (VerificationStatus.INSUFFICIENT_EVIDENCE, ReasonCode.EVIDENCE_MISSING, RecoveryHint.RE_OBSERVE)
    elif unmet:
        outcome = (VerificationStatus.REFUTED, ReasonCode.GOAL_NOT_SATISFIED, RecoveryHint.RETRY_ACTION)
    else:
        outcome = (VerificationStatus.CONFIRMED, ReasonCode.GOAL_SATISFIED, RecoveryHint.NONE)
    return _result(state, task_id, claim, *outcome, "workspace-clearance-v1")
