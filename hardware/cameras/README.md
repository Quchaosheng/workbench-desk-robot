# cameras

Camera drivers that produce `observation.schema.json`.

Supported (planned):
- USB camera (V4L2 / OpenCV)
- Intel RealSense D435 (depth + colour)
- event camera (stub for future)

**What to implement**: a ROS 2 node that reads from the device and publishes
`/observations` with the same `observation.schema.json` contract used in
Gazebo simulation.

Calibration files go in `cameras/calibration/`.
