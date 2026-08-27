# Rootfs and Services

The rootfs must boot the single Linux board into a non-actuating state. ROS 2,
the CAN gateway, diagnostics and update service are separate systemd units with
explicit dependencies and bounded restart behavior.

Required service boundaries:

- `robot-can-gateway`: SocketCAN ingress/egress and six-domain health;
- `robot-safety-monitor`: read-only mirror of `MCU-SAFETY`, never the safety authority;
- `robot-device-manager`: enumeration, firmware compatibility and diagnostics;
- `robot-camera-head`: serial-bound D435 ROS 2 input with no control authority;
- `robot-evidence-logger`: append-only local evidence with rotation limits;
- `robot-update-agent`: signed bundle verification and rollback.

No service may enable actuators during boot. A missing or incompatible MCU
firmware bundle must leave all motion domains inhibited.

`camera-head-deployment.yaml` is the fail-closed camera installation manifest.
The checked-in systemd unit is a template, not an assertion that the target is
ready. Freeze JetPack/L4T, ROS 2, `librealsense2` and `realsense2_camera`
versions and replace the purchased-unit serial before enabling it. D435 is a
multi-interface USB device, so bind it through the librealsense serial selector
and vendor udev rules; do not create one shared symlink for its `/dev/video*`
nodes.
