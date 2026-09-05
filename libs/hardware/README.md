# Hardware (#14) - Embedded Control Layer

## Overview

嵌入式工程师 P1 模块。当前实现 HW1 的展开 URDF 参数提取；HW2-HW7 仍是后续任务。

## Components

- **HW1**: URDF Parser (implemented)
- **HW2**: Bounded CAN transport adapter (host-side, fake-transport verified)
- **HW3**: Motor Feedback Parser (planned)
- **HW4**: PID Controller (planned)
- **HW5**: Sensor Simulator (planned)
- **HW6**: Realtime Executor (planned)
- **HW7**: Integration Test Framework (planned)

## Architecture

```
Kernel (ROS 2) 
    ↓ (versioned messages)
Hardware Layer
    ├─ URDF Parser → Motor Config
    ├─ DeviceRuntime
    │   └─ CAN DeviceAdapter ↔ injected CAN Wire V1 transport
    ├─ Motor Feedback ← Encoders
    ├─ PID Controller → Motor Command
    ├─ Sensor Simulator ← Gazebo
    └─ Realtime Executor (100Hz)
```

## SocketCAN ingress (Issue #229)

The host adapter can be backed by the standard-library
`workbench.hardware.SocketCANTransport`, which owns one Linux
`AF_CAN`/`CAN_RAW` descriptor. It uses kernel filters, bounded `poll`/
`recvmsg`, Classic CAN frame validation, `SO_TIMESTAMPNS` and
`SO_RXQ_OVFL` metadata. `DeviceRuntime` remains the sole owner of lifecycle,
worker and bounded data planes; the adapter does not add another queue or
worker.

Validated inbound ACK, STOP_ACK and telemetry frames produce immutable,
read-only `CanExternalRecord` values. These records contain source/interface,
ingress sequence, DLC, raw ID flags, timestamps, protocol fields, health and
an evidence reference. Invalid, duplicate, late, uncorrelated, error and
post-shutdown frames remain observable through the receive result and
diagnostics while the runtime is active, but cannot enter the external queue or
become externally exposed completion events.

The reproducible virtual probe is:

```bash
python3 kernel/wbcan/test_socketcan_ingress.py wbcan0 \
  --report /tmp/wbcan-socketcan-ingress-report.json
```

It emits `PASS`, `FAIL` or `NOT_EXECUTED` and labels physical CAN, MCU,
actuator and hard-real-time evidence as `NOT_EXECUTED`. See the
[`SocketCAN architecture contract`](../../docs/architecture/host-can-transport-v1.md)
and the [physical bring-up procedure](../../docs/hardware/can_bring_up.md).

## HW1 usage

The parser consumes expanded URDF XML, not Xacro source. Generate an official
UR5e description and extract the six arm joints:

```bash
source /opt/ros/jazzy/setup.bash
xacro /opt/ros/jazzy/share/ur_description/urdf/ur.urdf.xacro \
  ur_type:=ur5e name:=ur5e > /tmp/ur5e.urdf
python3 libs/hardware/urdf_to_motor_config.py /tmp/ur5e.urdf \
  --joint shoulder_pan_joint \
  --joint shoulder_lift_joint \
  --joint elbow_joint \
  --joint wrist_1_joint \
  --joint wrist_2_joint \
  --joint wrist_3_joint
```

`max_torque_nm`, velocity and position limits come from each URDF `<limit>`.
`mechanical_reduction` is populated only when an explicit URDF transmission
declares it. `null` means the controlled input did not declare a reduction; it
must not be replaced with a guessed physical gearbox ratio.

The audited official-source extraction command, package versions, hashes and
generated motor configuration are recorded in
[`docs/hardware/hw1-ur5e-extraction.md`](../../docs/hardware/hw1-ur5e-extraction.md).

## P1 Deliverables

- HW1: Motor configuration from expanded URDF (implemented)
- HW2: bounded host CAN `DeviceAdapter` hosted by the unified `DeviceRuntime`
  (implemented; physical transport not claimed)
- HW3: CAN feedback parsing (planned)
- HW4: PID controller (planned)
- HW5-6: Sensor simulation + 100Hz real-time control loop (planned)
- HW7: Full integration test (planned)

The CAN adapter does not create its own worker or lifecycle. `DeviceRuntime`
owns `configure -> activate -> deactivate -> cleanup`, cancellation, the
single I/O worker, bounded command/ACK, telemetry and health planes, and the
subscriber snapshot. `SafeCANBus` compatibility lifecycle methods delegate to
that owner. See
[`host-can-transport-v1.md`](../../docs/architecture/host-can-transport-v1.md)
for the exact ownership and evidence boundary.
