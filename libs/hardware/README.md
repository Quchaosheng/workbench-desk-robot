# Hardware (#14) - Embedded Control Layer

## Overview

嵌入式工程师 P1 实现 (HW1-HW7)

## Components

- **HW1**: URDF Parser (extract motor parameters)
- **HW2**: CAN Driver (communicate with MCU)
- **HW3**: Motor Feedback Parser (position/velocity/current)
- **HW4**: PID Controller (closed-loop control)
- **HW5**: Sensor Simulator (read from Gazebo)
- **HW6**: Realtime Executor (100Hz control loop)
- **HW7**: Integration Test Framework

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

## Key Features

- **100Hz control loop**: Real-time execution with thread-based scheduling
- **CAN communication**: Versioned message protocol (via K4-K5 from kernel)
- **Motor feedback**: Position, velocity, current parsing
- **PID control**: Closed-loop feedback control
- **Sensor integration**: IMU + joint states from Gazebo

## Usage

```python
from workbench.hardware.realtime_executor import RealtimeExecutor
from workbench.hardware.pid_controller import PIDController

executor = RealtimeExecutor(frequency=100)
pid = PIDController(kp=10, ki=0.1, kd=1)

def control_loop():
    output = pid.compute(setpoint=1.0, feedback=0.5)
    # send to motor via CAN

executor.add_task(control_loop)
executor.start()
```

## P1 Deliverables

- HW1: Motor configuration from URDF
- HW2-3: CAN communication + feedback parsing
- HW4: PID controller tested
- HW5-6: 100Hz real-time control loop
- HW7: Full integration test passing

All tests passing. Ready for P1 application layer integration.
