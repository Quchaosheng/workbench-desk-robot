# Robot BSP Head Camera V0.1

The cost-conscious prototype uses one Intel RealSense D435 RGB-D camera in the
head. It provides workspace observation and depth without buying two wrist
cameras before an occlusion study shows that they are necessary.

The D435 is a USB device. The Linux BSP does not need a new robot-specific
kernel driver: the kernel boundary is `uvcvideo`/V4L2, while depth processing
uses `librealsense2` and ROS 2 integration uses `realsense2_camera`. Exact
package versions must match the selected JetPack release and are not frozen
until that compatibility test runs.

## Integration chain

```text
RealSense D435 -> USB 3 -> uvcvideo / V4L2 -> librealsense2
              -> realsense2_camera -> validated observation adapter
              -> evidence/event path
```

The camera node publishes sensor data; it does not directly produce verified
task completion. Calibration, timestamp quality, frame identity and observation
validation remain explicit boundaries.

## Bring-up gates

1. Confirm the purchased serial number, USB 3 topology, cable retention and
   sustained bandwidth alongside the other Jetson USB devices.
2. Confirm the physical D435 envelope against the head mount. The existing
   simulated `camera_body` geometry is not a supplier drawing.
3. Record color/depth modes, drop counters, timestamp source and CPU/GPU cost.
4. Generate real intrinsics and robot extrinsics; never copy Gazebo intrinsics.
5. Validate low light, reflective surfaces, minimum range, occlusion and camera
   dropout before using frames as physical evidence.
6. Add wrist cameras only if measured task coverage cannot meet the acceptance
   threshold with head motion and the single D435.

Until these gates close, status is
`RECOMMENDED_SELECTION_PHYSICAL_CAMERA_EVIDENCE_NOT_EXECUTED`.
