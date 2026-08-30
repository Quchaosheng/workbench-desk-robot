# Perception (Owner: Perception)

P0 emits `Observation` from a controlled Gazebo camera using OpenCV plus AprilTag or color recognition. Required fields are documented in `interfaces/json_schema/observation.schema.json`.

Do not use simulator Oracle values in sensor-mode metrics.

`workbench_perception.ObservationIngestionAdapter` is the fail-closed boundary
between an Observation producer and the World Model event stream. Callers must
name an approved camera calibration revision and pose unit, and inject a clock
from the same domain as the Observation. The adapter rejects malformed, stale,
future-skewed, low-confidence, duplicate, uncalibrated, and frame-mismatched
records before invoking its World Model sink. It preserves the unmodified JSON
Observation under `payload.raw_observation` and emits the calibrated pose at
`payload.pose`; it never writes `WorldState` facts directly.

## Known-target RGB-D software producer

`workbench_perception.KnownTargetRgbdProducer` implements the deterministic
software portion of Issue #158. It accepts typed RGB, aligned-depth, camera
intrinsics and AprilTag detections for an explicit entity allow-list. Unknown
tags are reported separately and never assigned a guessed identity. Missing or
invalid depth, stale or unsynchronised frames, clock mismatch, duplicate tags,
occlusion, and low-margin detections fail closed before any Observation or
evidence record is published.

The producer returns the existing contract `Observation` plus the camera ID,
calibration revision, and pose units required by the Issue #72 ingestion
adapter. Recent evidence references resolve to immutable hashes and frame
metadata in a bounded store; raw RGB/depth payloads are never embedded in an
Observation or WorldEvent.

Physical status remains **NOT_EXECUTED**. The repository contains no serialized
camera, firmware revision, calibration artifact/hash, measured clock
offset/drift, real ROS launch capture, fixture ground truth, or target-hardware
latency/CPU/memory output. This software module and its local fixtures are not
evidence of a connected Intel RealSense D435 or successful real perception.
