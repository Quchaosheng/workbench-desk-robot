from __future__ import annotations

import json
import math
import sys
import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "libs/contracts"), str(ROOT / "services/perception")]

from workbench_contracts import ClockId, WorldEventType
from workbench_perception import CalibrationRecord, ObservationIngestionAdapter, ObservationRejected

NOW = datetime(2026, 8, 28, 4, 0, 1, tzinfo=UTC)


def observation_record(**updates: object) -> dict[str, object]:
    record: dict[str, object] = {
        "observation_id": "obs-001",
        "run_id": "run-001",
        "entity_id": "red_block",
        "entity_type": "block",
        "pose": {
            "frame_id": "camera_optical",
            "position": {"x": 0.2, "y": 0.1, "z": 0.02},
            "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        },
        "confidence": 0.98,
        "detector": "apriltag",
        "hamming": 0,
        "decision_margin": 72.5,
        "observed_at": "2026-08-28T04:00:00Z",
        "clock_id": "wall",
        "source": "camera-01",
        "evidence_refs": ["frame://camera-01/001"],
    }
    record.update(updates)
    return record


def calibration(**updates: object) -> CalibrationRecord:
    values: dict[str, object] = {
        "camera_id": "camera-01",
        "revision": "cal-v1",
        "source_frame": "camera_optical",
        "target_frame": "workbench",
        "clock_id": ClockId.WALL,
        "translation_m": (1.0, 2.0, 3.0),
    }
    values.update(updates)
    return CalibrationRecord(**values)  # type: ignore[arg-type]


def adapter(*, sink=None, **updates: object) -> ObservationIngestionAdapter:
    values: dict[str, object] = {
        "now": lambda _clock_id: NOW,
        "sink": sink,
        "minimum_confidence": 0.7,
        "maximum_age": timedelta(seconds=2),
        "maximum_future_skew": timedelta(milliseconds=100),
    }
    values.update(updates)
    return ObservationIngestionAdapter([calibration()], **values)  # type: ignore[arg-type]


def ingest(target: ObservationIngestionAdapter, record: dict[str, object] | None = None, **updates: object):
    context: dict[str, object] = {
        "camera_id": "camera-01",
        "calibration_revision": "cal-v1",
        "pose_units": "m",
        "sequence_no": 0,
    }
    context.update(updates)
    return target.ingest(observation_record() if record is None else record, **context)  # type: ignore[arg-type]


class CalibrationRecordTests(unittest.TestCase):
    def test_calibration_requires_bounded_rigid_transform(self) -> None:
        invalid_updates = (
            {"camera_id": ""},
            {"camera_id": 1},
            {"clock_id": "wall"},
            {"translation_m": 1.0},
            {"translation_m": (0.0, math.nan, 0.0)},
            {"rotation_xyzw": [0.0, 0.0, 0.0, 1.0]},
            {"rotation_xyzw": (0.0, 0.0, 0.0, 0.0)},
            {"pose_units": "cm"},
        )

        for updates in invalid_updates:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                calibration(**updates)


class ObservationIngestionTests(unittest.TestCase):
    def test_valid_observation_is_calibrated_and_delivered(self) -> None:
        delivered = []
        target = adapter(sink=delivered.append)

        event = ingest(target)

        self.assertEqual(delivered, [event])
        self.assertEqual(event.event_type, WorldEventType.OBSERVATION)
        self.assertEqual(event.event_id, "observation:obs-001")
        self.assertEqual(event.payload["pose"]["frame_id"], "workbench")
        self.assertEqual(event.payload["pose"]["position"], {"x": 1.2, "y": 2.1, "z": 3.02})
        self.assertEqual(event.payload["calibration_revision"], "cal-v1")
        self.assertEqual(event.evidence_refs, ["frame://camera-01/001"])

    def test_world_event_satisfies_current_contract(self) -> None:
        event = ingest(adapter()).model_dump(mode="json")
        schema_path = ROOT / "interfaces/json_schema/world_event.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(event)

    def test_raw_provenance_is_preserved_and_detached(self) -> None:
        record = observation_record(vendor_metadata={"exposure_us": 5000})
        original = deepcopy(record)
        event = ingest(adapter(), record)
        record["entity_id"] = "mutated"
        record["evidence_refs"].append("frame://mutated")  # type: ignore[union-attr]

        self.assertEqual(event.payload["raw_observation"], original)

    def test_dropout_and_contract_invalid_records_fail_closed(self) -> None:
        target = adapter()
        with self.assertRaises(ObservationRejected):
            target.ingest(
                None,
                camera_id="camera-01",
                calibration_revision="cal-v1",
                pose_units="m",
                sequence_no=0,
            )

        invalid_records = [
            {},
            {key: value for key, value in observation_record().items() if key != "source"},
            observation_record(confidence="0.98"),
            observation_record(hamming=-1),
            observation_record(decision_margin=float("nan")),
        ]

        for record in invalid_records:
            with self.subTest(record=record), self.assertRaises(ObservationRejected):
                ingest(adapter(), record)  # type: ignore[arg-type]

    def test_malformed_pose_is_rejected(self) -> None:
        invalid_poses = [
            {
                "frame_id": "camera_optical",
                "position": {"x": float("nan"), "y": 0.0, "z": 0.0},
                "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
            },
            {
                "frame_id": "camera_optical",
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 0.0},
            },
        ]

        for pose in invalid_poses:
            with self.subTest(pose=pose), self.assertRaises(ObservationRejected):
                ingest(adapter(), observation_record(pose=pose))

    def test_confidence_and_freshness_gates_fail_closed(self) -> None:
        invalid_records = (
            observation_record(confidence=0.69),
            observation_record(observed_at="2026-08-28T03:59:58Z"),
            observation_record(observed_at="2026-08-28T04:00:01.101Z"),
            observation_record(observed_at="not-a-timestamp"),
            observation_record(observed_at="2026-08-28T04:00:00"),
        )

        for record in invalid_records:
            with self.subTest(record=record), self.assertRaises(ObservationRejected):
                ingest(adapter(), record)

    def test_camera_calibration_units_clock_and_frames_are_validated(self) -> None:
        cases = (
            (observation_record(), {"camera_id": "camera-02"}),
            (observation_record(), {"calibration_revision": "missing"}),
            (observation_record(), {"pose_units": "cm"}),
            (observation_record(clock_id="monotonic"), {}),
            (
                observation_record(
                    pose={
                        "frame_id": "unknown_frame",
                        "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                        "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
                    }
                ),
                {},
            ),
        )

        for record, context in cases:
            with self.subTest(context=context), self.assertRaises(ObservationRejected):
                ingest(adapter(), record, **context)

    def test_target_frame_pose_is_not_transformed_again(self) -> None:
        pose = {
            "frame_id": "workbench",
            "position": {"x": 0.2, "y": 0.1, "z": 0.02},
            "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        }

        event = ingest(adapter(), observation_record(pose=pose))

        self.assertEqual(event.payload["pose"], pose)

    def test_duplicate_ids_and_entity_frames_are_rejected(self) -> None:
        target = adapter()
        ingest(target)

        with self.assertRaisesRegex(ObservationRejected, "observation_id"):
            ingest(target)
        with self.assertRaisesRegex(ObservationRejected, "camera-frame"):
            ingest(target, observation_record(observation_id="obs-002"), sequence_no=1)

    def test_invalid_observations_never_reach_world_model_sink(self) -> None:
        delivered = []
        target = adapter(sink=delivered.append)

        with self.assertRaises(ObservationRejected):
            ingest(target, observation_record(confidence=0.1))

        self.assertEqual(delivered, [])

    def test_duplicate_tracking_is_bounded(self) -> None:
        target = adapter(duplicate_window_size=1)
        ingest(target)
        ingest(
            target,
            observation_record(
                observation_id="obs-002",
                entity_id="blue_block",
                evidence_refs=["frame://camera-01/002"],
            ),
            sequence_no=1,
        )

        event = ingest(target, sequence_no=2)

        self.assertEqual(event.event_id, "observation:obs-001")

    def test_adapter_configuration_rejects_unsafe_values(self) -> None:
        with self.assertRaises(ValueError):
            ObservationIngestionAdapter([], now=lambda _clock: NOW)
        with self.assertRaises(ValueError):
            adapter(minimum_confidence=float("nan"))
        with self.assertRaises(ValueError):
            adapter(maximum_age=timedelta(seconds=-1))
        with self.assertRaises(ValueError):
            adapter(duplicate_window_size=0)
        with self.assertRaises(ValueError):
            adapter(duplicate_window_size=1.5)
        with self.assertRaises(ValueError):
            ObservationIngestionAdapter([object()], now=lambda _clock: NOW)  # type: ignore[list-item]


if __name__ == "__main__":
    unittest.main()
