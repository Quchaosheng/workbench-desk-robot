import hashlib

_FIXED_TIMESTAMP = "2026-08-04T00:00:16.200Z"


def mock_world_state(run_id: str) -> dict[str, object]:
    """Return deterministic, Schema-shaped WorldState data for development consumers."""
    return {
        "run_id": run_id,
        "sequence_no": 31,
        "state_hash": hashlib.sha256(f"mock-world-state:{run_id}".encode()).hexdigest(),
        "entities": [
            {
                "entity_id": "red_block",
                "entity_type": "block",
                "pose": {
                    "frame_id": "table",
                    "position": {"x": 0.31, "y": -0.04, "z": 0.035},
                    "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
                },
                "belief": "observed",
                "confidence": 0.96,
                "last_observed_at": "2026-08-04T00:00:16.100Z",
                "evidence_refs": ["obs-mock-block"],
            },
            {
                "entity_id": "tray",
                "entity_type": "tray",
                "pose": {
                    "frame_id": "table",
                    "position": {"x": 0.30, "y": -0.05, "z": 0.0},
                    "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
                },
                "belief": "observed",
                "confidence": 0.99,
                "last_observed_at": "2026-08-04T00:00:16.100Z",
                "evidence_refs": ["obs-mock-tray"],
            },
        ],
        "relations": [
            {
                "subject_id": "red_block",
                "predicate": "inside",
                "object_id": "tray",
                "belief": "observed",
                "evidence_refs": ["obs-mock-block", "obs-mock-tray"],
            }
        ],
        "reduced_at": _FIXED_TIMESTAMP,
        "clock_id": "monotonic",
    }


def mock_verification(status: str) -> dict[str, object]:
    """Return deterministic, Schema-shaped VerificationResult data."""
    outcomes = {
        "confirmed": {
            "claim": "red_block inside tray",
            "reason_code": "goal_satisfied",
            "completeness": 1.0,
            "recovery_hint": "none",
        },
        "refuted": {
            "claim": "red_block inside tray",
            "reason_code": "goal_not_satisfied",
            "completeness": 1.0,
            "recovery_hint": "retry_action",
        },
        "insufficient_evidence": {
            "claim": "red_block inside tray could not be verified",
            "reason_code": "target_not_observed",
            "completeness": 0.5,
            "recovery_hint": "re_observe",
        },
    }
    try:
        outcome = outcomes[status]
    except KeyError as exc:
        raise ValueError(f"unsupported verification status: {status}") from exc

    return {
        "verification_id": f"ver-mock-{status}",
        "run_id": "run-mock-001",
        "task_id": "task-mock-001",
        "claim": outcome["claim"],
        "status": status,
        "reason_code": outcome["reason_code"],
        "completeness": outcome["completeness"],
        "evidence_refs": ["evidence-mock-001"],
        "recovery_hint": outcome["recovery_hint"],
        "verified_at": _FIXED_TIMESTAMP,
        "clock_id": "monotonic",
    }
