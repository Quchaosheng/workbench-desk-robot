from workbench_contracts import VerificationResult

from .reducer import WorldState


def verify_object_in_tray(
    state: WorldState, task_id: str, object_id: str, tray_id: str
) -> VerificationResult:
    expected_location = f"in:{tray_id}"
    actual_location = state.entity_locations.get(object_id)
    completed = actual_location == expected_location
    reason = (
        "object location matches tray relation"
        if completed
        else f"expected {expected_location}, got {actual_location}"
    )
    return VerificationResult(
        task_id=task_id,
        completed=completed,
        reason=reason,
        rule_version="tray-membership-v1",
        evidence_refs=state.evidence_refs,
    )
