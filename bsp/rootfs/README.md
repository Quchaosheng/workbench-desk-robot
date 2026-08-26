# Rootfs and Services

The rootfs must boot the single Linux board into a non-actuating state. ROS 2,
the CAN gateway, diagnostics and update service are separate systemd units with
explicit dependencies and bounded restart behavior.

Required service boundaries:

- `robot-can-gateway`: SocketCAN ingress/egress and six-domain health;
- `robot-safety-monitor`: read-only mirror of `MCU-SAFETY`, never the safety authority;
- `robot-device-manager`: enumeration, firmware compatibility and diagnostics;
- `robot-evidence-logger`: append-only local evidence with rotation limits;
- `robot-update-agent`: signed bundle verification and rollback.

No service may enable actuators during boot. A missing or incompatible MCU
firmware bundle must leave all motion domains inhibited.
