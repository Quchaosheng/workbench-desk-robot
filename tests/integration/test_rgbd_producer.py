from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "libs/contracts"), str(ROOT / "services/perception")]

from workbench_contracts import ClockId, WorldEventType
from workbench_perception import (
    CalibrationRecord,
    CameraIntrinsics,
    DepthFrame,
    FrameEvidenceStore,
    KnownEntity,
    KnownTargetRgbdProducer,
    ObservationIngestionAdapter,
    RgbFrame,
    TagDetection,
)


def test_rgbd_output_passes_issue_72_ingestion_boundary() -> None:
    now = datetime(2026, 8, 30, 4, 0, 0, tzinfo=UTC)
    producer = KnownTargetRgbdProducer(
        [KnownEntity(tag_id=12, entity_id="parcel_fixture", entity_type="parcel")],
        now=lambda clock_id: now,
        evidence_store=FrameEvidenceStore(),
    )
    produced = producer.produce(
        run_id="run-rgbd-integration",
        rgb=RgbFrame(
            sequence_no=1,
            width=2,
            height=2,
            observed_at=now - timedelta(milliseconds=5),
            clock_id=ClockId.WALL,
            data=bytes(range(12)),
        ),
        depth=DepthFrame(
            sequence_no=1,
            width=2,
            height=2,
            observed_at=now - timedelta(milliseconds=4),
            clock_id=ClockId.WALL,
            depth_m=((1.0, 1.0), (1.0, 1.0)),
        ),
        intrinsics=CameraIntrinsics(
            camera_id="camera-d435-front",
            calibration_revision="cal-not-executed-fixture-v1",
            frame_id="camera_color_optical_frame",
            width=2,
            height=2,
            fx=2.0,
            fy=2.0,
            cx=0.5,
            cy=0.5,
            clock_id=ClockId.WALL,
        ),
        detections=[TagDetection(tag_id=12, center_x=0.5, center_y=0.5, decision_margin=90.0)],
    ).observations[0]
    events = []
    ingestion = ObservationIngestionAdapter(
        [
            CalibrationRecord(
                camera_id="camera-d435-front",
                revision="cal-not-executed-fixture-v1",
                source_frame="camera_color_optical_frame",
                target_frame="table",
                clock_id=ClockId.WALL,
                translation_m=(0.1, 0.2, 0.3),
            )
        ],
        now=lambda clock_id: now,
        sink=events.append,
    )

    event = ingestion.ingest(
        produced.observation.model_dump(mode="json"),
        camera_id=produced.camera_id,
        calibration_revision=produced.calibration_revision,
        pose_units=produced.pose_units,
        sequence_no=1,
    )

    assert event.event_type is WorldEventType.OBSERVATION
    assert event.payload["pose"]["frame_id"] == "table"
    assert event.payload["calibration_revision"] == "cal-not-executed-fixture-v1"
    assert events == [event]
