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
