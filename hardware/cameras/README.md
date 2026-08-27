# cameras

Camera integrations that feed validated `observation.schema.json` producers.

Selected prototype baseline:
- one head-mounted Intel RealSense D435 over USB 3;
- Linux `uvcvideo`/V4L2 kernel boundary;
- `librealsense2` userspace depth processing;
- ROS 2 `realsense2_camera` device node;
- exact serial, stream modes, JetPack-compatible package versions and physical
  calibration remain `NOT_EXECUTED` until hardware is available.

Other integrations:
- USB camera (V4L2 / OpenCV)
- event camera (stub for future)

**What to implement**: a ROS 2 node that reads from the device and publishes
`/observations` with the same `observation.schema.json` contract used in
Gazebo simulation.

Calibration files go in `cameras/calibration/`. Gazebo intrinsics and frame
geometry are not valid physical calibration. The BSP selection and gates are
defined in `bsp/sensors/camera-head.yaml` and
`docs/architecture/robot-bsp-camera-v0.1.md`.
