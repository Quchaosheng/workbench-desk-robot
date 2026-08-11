# Hardware (#14) - Embedded Control Layer

## Overview

嵌入式工程师 P1 模块。当前实现 HW1 的展开 URDF 参数提取；HW2-HW7 仍是后续任务。

## Components

- **HW1**: URDF Parser (implemented)
- **HW2**: CAN Driver (planned)
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
    ├─ CAN Driver ↔ MCU
    ├─ Motor Feedback ← Encoders
    ├─ PID Controller → Motor Command
    ├─ Sensor Simulator ← Gazebo
    └─ Realtime Executor (100Hz)
```

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

## P1 Deliverables

- HW1: Motor configuration from expanded URDF (implemented)
- HW2-3: CAN communication + feedback parsing (planned)
- HW4: PID controller (planned)
- HW5-6: Sensor simulation + 100Hz real-time control loop (planned)
- HW7: Full integration test (planned)
