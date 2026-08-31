from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "libs/contracts"),
    str(ROOT / "services/world_model"),
    str(ROOT / "tools/scripts"),
]

from collect_metrics import canonical_replay_hash, collect


def event(
    *,
    event_id: str,
    sequence_no: int,
    run_id: str = "run-canonical-metrics",
    confidence: float = 0.9,
    location: str = "on:table",
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "run_id": run_id,
        "sequence_no": sequence_no,
        "event_type": "observation",
        "occurred_at": f"2026-08-30T00:00:{sequence_no:02d}Z",
        "payload": {
            "entity_id": "parcel_fixture",
            "entity_type": "parcel",
            "location": location,
            "confidence": confidence,
            "attributes": {"label_status": "verified"},
        },
        "evidence_refs": [f"frame://{event_id}"],
    }


def write_run(path: Path, events: list[dict[str, object]]) -> None:
    path.write_text("".join(f"{json.dumps(item)}\n" for item in events), encoding="utf-8")


def test_state_hash_comes_from_canonical_world_state_and_is_permutation_stable() -> None:
    events = [event(event_id="obs-0", sequence_no=0), event(event_id="obs-5", sequence_no=5, confidence=0.8)]

    assert canonical_replay_hash(events) == canonical_replay_hash(list(reversed(events)))


def test_semantically_different_observation_changes_canonical_state_hash() -> None:
    baseline = [event(event_id="obs-0", sequence_no=0, confidence=0.9)]
    changed = deepcopy(baseline)
    changed_payload = changed[0]["payload"]
    assert isinstance(changed_payload, dict)
    changed_payload["confidence"] = 0.4

    assert canonical_replay_hash(baseline) != canonical_replay_hash(changed)


def test_non_contiguous_but_valid_canonical_stream_counts_as_success(tmp_path: Path) -> None:
    write_run(
        tmp_path / "run.jsonl",
        [event(event_id="obs-2", sequence_no=2), event(event_id="obs-9", sequence_no=9, confidence=0.8)],
    )

    metrics = collect(tmp_path)

    assert metrics["replay_success_rate"] == 1.0
    assert metrics["state_hash_consistency"] == 1.0


@pytest.mark.parametrize(
    ("events", "message"),
    [
        (
            [event(event_id="obs-0", sequence_no=0), event(event_id="obs-1", sequence_no=1, run_id="other")],
            "does not match requested run_id",
        ),
        (
            [event(event_id="obs-0", sequence_no=0), event(event_id="obs-1", sequence_no=0)],
            "sequence_no 0 is shared",
        ),
        (
            [{**event(event_id="obs-0", sequence_no=0), "unexpected": True}],
            "Extra inputs are not permitted",
        ),
        (
            [event(event_id="obs-0", sequence_no=0, location="beside:table")],
            "cannot be represented",
        ),
    ],
)
def test_invalid_or_unreplayable_streams_fail_closed(
    tmp_path: Path, events: list[dict[str, object]], message: str
) -> None:
    write_run(tmp_path / "run.jsonl", events)

    with pytest.raises(RuntimeError, match=message):
        collect(tmp_path)


def test_malformed_json_and_duplicate_run_ownership_fail_closed(tmp_path: Path) -> None:
    (tmp_path / "bad.jsonl").write_text("{bad-json}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unreadable JSONL"):
        collect(tmp_path)

    (tmp_path / "bad.jsonl").unlink()
    values = [event(event_id="obs-0", sequence_no=0)]
    write_run(tmp_path / "first.jsonl", values)
    write_run(tmp_path / "second.jsonl", values)
    with pytest.raises(RuntimeError, match="owned by more than one event log"):
        collect(tmp_path)


def test_legacy_evaluation_envelope_and_non_contract_event_type_fail_closed(tmp_path: Path) -> None:
    legacy = event(event_id="evt-0", sequence_no=0)
    legacy["evaluation"] = {"runner": "scripted"}
    write_run(tmp_path / "legacy.jsonl", [legacy])
    with pytest.raises(RuntimeError, match="Extra inputs are not permitted"):
        collect(tmp_path)

    legacy.pop("evaluation")
    legacy["event_type"] = "task_graph"
    write_run(tmp_path / "legacy.jsonl", [legacy])
    with pytest.raises(RuntimeError, match="event_type"):
        collect(tmp_path)
