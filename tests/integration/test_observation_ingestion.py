from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "libs/contracts"),
    str(ROOT / "services/perception"),
    str(ROOT / "services/world_model"),
]

from workbench_contracts import ClockId
from workbench_perception import CalibrationRecord, ObservationIngestionAdapter, ObservationRejected
from workbench_world_model import reduce_events


def test_world_model_receives_only_accepted_observations() -> None:
    accepted_events = []
    adapter = ObservationIngestionAdapter(
        [
            CalibrationRecord(
                camera_id="camera-01",
                revision="cal-v1",
                source_frame="camera_optical",
                target_frame="workbench",
                clock_id=ClockId.WALL,
            )
        ],
        now=lambda _clock_id: datetime(2026, 8, 28, 4, 0, 1, tzinfo=UTC),
        sink=accepted_events.append,
        minimum_confidence=0.8,
        maximum_age=timedelta(seconds=2),
    )
    valid_record = {
        "observation_id": "obs-valid",
        "run_id": "run-observation",
        "entity_id": "red_block",
        "entity_type": "block",
        "pose": {
            "frame_id": "camera_optical",
            "position": {"x": 0.2, "y": 0.1, "z": 0.02},
            "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        },
        "confidence": 0.95,
        "detector": "apriltag",
        "observed_at": "2026-08-28T04:00:00Z",
        "clock_id": "wall",
        "source": "camera-01",
        "evidence_refs": ["frame://camera-01/valid"],
    }

    adapter.ingest(
        valid_record,
        camera_id="camera-01",
        calibration_revision="cal-v1",
        pose_units="m",
        sequence_no=0,
    )
    with pytest.raises(ObservationRejected):
        adapter.ingest(
            {**valid_record, "observation_id": "obs-low", "confidence": 0.2},
            camera_id="camera-01",
            calibration_revision="cal-v1",
            pose_units="m",
            sequence_no=1,
        )

    state = reduce_events("run-observation", accepted_events)

    assert len(accepted_events) == 1
    assert state.applied_event_ids == ["observation:obs-valid"]
    assert state.entity_confidence == {"red_block": 0.95}
    assert state.entity_evidence_refs == {"red_block": ["frame://camera-01/valid"]}
