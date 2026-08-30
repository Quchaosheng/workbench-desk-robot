from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "libs/contracts"), str(ROOT / "services/perception")]

from workbench_contracts import ClockId, Observation
from workbench_perception import (
    CameraIntrinsics,
    DepthFrame,
    FrameEvidenceStore,
    KnownEntity,
    KnownTargetRgbdProducer,
    RgbdObservationRejected,
    RgbFrame,
    TagDetection,
)

NOW = datetime(2026, 8, 30, 4, 0, 0, tzinfo=UTC)


def intrinsics(**changes: object) -> CameraIntrinsics:
    values = {
        "camera_id": "camera-d435-front",
        "calibration_revision": "cal-not-executed-fixture-v1",
        "frame_id": "camera_color_optical_frame",
        "width": 3,
        "height": 3,
        "fx": 2.0,
        "fy": 2.0,
        "cx": 1.0,
        "cy": 1.0,
        "clock_id": ClockId.WALL,
    }
    values.update(changes)
    return CameraIntrinsics(**values)  # type: ignore[arg-type]


def rgb(**changes: object) -> RgbFrame:
    values = {
        "sequence_no": 7,
        "width": 3,
        "height": 3,
        "observed_at": NOW - timedelta(milliseconds=10),
        "clock_id": ClockId.WALL,
        "data": bytes(range(27)),
    }
    values.update(changes)
    return RgbFrame(**values)  # type: ignore[arg-type]


def depth(**changes: object) -> DepthFrame:
    values = {
        "sequence_no": 7,
        "width": 3,
        "height": 3,
        "observed_at": NOW - timedelta(milliseconds=5),
        "clock_id": ClockId.WALL,
        "depth_m": ((1.0, 1.0, 1.0), (1.0, 2.0, 1.0), (1.0, 1.0, 1.0)),
    }
    values.update(changes)
    return DepthFrame(**values)  # type: ignore[arg-type]


def detection(**changes: object) -> TagDetection:
    values = {"tag_id": 12, "center_x": 1.0, "center_y": 1.0, "decision_margin": 90.0}
    values.update(changes)
    return TagDetection(**values)  # type: ignore[arg-type]


def producer(store: FrameEvidenceStore | None = None) -> KnownTargetRgbdProducer:
    return KnownTargetRgbdProducer(
        [KnownEntity(tag_id=12, entity_id="parcel_fixture", entity_type="parcel")],
        now=lambda clock_id: NOW,
        evidence_store=store if store is not None else FrameEvidenceStore(),
    )


def test_known_tag_produces_contract_observation_and_projected_pose() -> None:
    batch = producer().produce(
        run_id="run-rgbd-fixture", rgb=rgb(), depth=depth(), intrinsics=intrinsics(), detections=[detection()]
    )

    assert len(batch.observations) == 1
    produced = batch.observations[0]
    assert isinstance(produced.observation, Observation)
    assert produced.observation.entity_id == "parcel_fixture"
    assert produced.observation.pose.position.model_dump() == {"x": 0.0, "y": 0.0, "z": 2.0}
    assert produced.observation.source == "camera-d435-front"
    assert produced.observation.evidence_refs == [batch.evidence_ref]
    assert produced.calibration_revision == "cal-not-executed-fixture-v1"
    assert produced.pose_units == "m"


def test_unknown_tag_is_reported_without_guessed_identity() -> None:
    batch = producer().produce(
        run_id="run-rgbd-fixture",
        rgb=rgb(),
        depth=depth(),
        intrinsics=intrinsics(),
        detections=[detection(tag_id=999)],
    )

    assert batch.observations == ()
    assert batch.ignored_tag_ids == (999,)


@pytest.mark.parametrize(
    "detections, message",
    [
        ([detection(), detection()], "duplicate tag"),
        ([detection(occluded=True)], "occluded"),
        ([detection(decision_margin=49.9)], "low decision margin"),
        ([detection(hamming=1)], "hamming"),
        ([detection(center_x=3.0)], "center_x"),
    ],
)
def test_bad_detections_fail_closed(detections: list[TagDetection], message: str) -> None:
    with pytest.raises(RgbdObservationRejected, match=message):
        producer().produce(
            run_id="run-rgbd-fixture",
            rgb=rgb(),
            depth=depth(),
            intrinsics=intrinsics(),
            detections=detections,
        )


@pytest.mark.parametrize("bad_depth", [0.0, float("nan"), float("inf"), 20.0])
def test_missing_or_invalid_aligned_depth_fails_closed(bad_depth: float) -> None:
    rows = ((1.0, 1.0, 1.0), (1.0, bad_depth, 1.0), (1.0, 1.0, 1.0))
    with pytest.raises(RgbdObservationRejected, match="invalid aligned depth"):
        producer().produce(
            run_id="run-rgbd-fixture",
            rgb=rgb(),
            depth=depth(depth_m=rows),
            intrinsics=intrinsics(),
            detections=[detection()],
        )


@pytest.mark.parametrize(
    "rgb_frame, depth_frame, calibration, message",
    [
        (rgb(), depth(sequence_no=8), intrinsics(), "sequence numbers"),
        (
            rgb(),
            depth(observed_at=NOW - timedelta(milliseconds=50)),
            intrinsics(),
            "unsynchronised",
        ),
        (
            rgb(observed_at=NOW - timedelta(seconds=2)),
            depth(observed_at=NOW - timedelta(seconds=2)),
            intrinsics(),
            "stale",
        ),
        (rgb(clock_id=ClockId.MONOTONIC), depth(), intrinsics(), "clock domains"),
        (rgb(), depth(), intrinsics(width=4), "dimensions"),
    ],
)
def test_invalid_frame_pairs_fail_closed(
    rgb_frame: RgbFrame, depth_frame: DepthFrame, calibration: CameraIntrinsics, message: str
) -> None:
    with pytest.raises(RgbdObservationRejected, match=message):
        producer().produce(
            run_id="run-rgbd-fixture",
            rgb=rgb_frame,
            depth=depth_frame,
            intrinsics=calibration,
            detections=[detection()],
        )


def test_evidence_is_deterministic_bounded_and_contains_no_raw_payload() -> None:
    first_store = FrameEvidenceStore(maximum_entries=1)
    first = producer(first_store).produce(
        run_id="run-rgbd-fixture", rgb=rgb(), depth=depth(), intrinsics=intrinsics(), detections=[detection()]
    )
    repeat_store = FrameEvidenceStore(maximum_entries=1)
    repeat = producer(repeat_store).produce(
        run_id="run-rgbd-fixture", rgb=rgb(), depth=depth(), intrinsics=intrinsics(), detections=[detection()]
    )
    assert first.evidence_ref == repeat.evidence_ref
    assert first.observations[0].observation.observation_id == repeat.observations[0].observation.observation_id
    evidence = first_store.resolve(first.evidence_ref)
    assert evidence is not None
    assert not hasattr(evidence, "data")
    assert not hasattr(evidence, "depth_m")
    assert len(evidence.rgb_sha256) == 64
    assert len(evidence.depth_sha256) == 64

    next_batch = producer(first_store).produce(
        run_id="run-rgbd-fixture",
        rgb=rgb(sequence_no=8, data=bytes(reversed(range(27)))),
        depth=depth(sequence_no=8),
        intrinsics=intrinsics(),
        detections=[detection()],
    )
    assert len(first_store) == 1
    assert first_store.resolve(first.evidence_ref) is None
    assert first_store.resolve(next_batch.evidence_ref) is not None


def test_same_running_producer_rejects_duplicate_frame_pair() -> None:
    target = producer()
    arguments = {
        "run_id": "run-rgbd-fixture",
        "rgb": rgb(),
        "depth": depth(),
        "intrinsics": intrinsics(),
        "detections": [detection()],
    }
    target.produce(**arguments)
    with pytest.raises(RgbdObservationRejected, match="duplicate RGB-D frame pair"):
        target.produce(**arguments)


def test_typed_inputs_are_not_mutated() -> None:
    rgb_frame = rgb()
    depth_frame = depth()
    calibration = intrinsics()
    tag = detection()
    before = (rgb_frame, depth_frame, calibration, tag)

    producer().produce(
        run_id="run-rgbd-fixture",
        rgb=rgb_frame,
        depth=depth_frame,
        intrinsics=calibration,
        detections=[tag],
    )

    assert before == (rgb_frame, depth_frame, calibration, tag)
