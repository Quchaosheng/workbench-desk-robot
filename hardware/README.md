# hardware

Real-hardware adapters. Each subdirectory wraps a physical device behind the same
contracts used in simulation, so swapping vcan for real CAN or a mock camera for
a USB camera doesn't change anything upstream.

```
hardware/
  can_adapters/     SocketCAN / USB-CAN bridges (CANable, PCAN, etc.)
  cameras/          USB, RGBD and event cameras
  arm_drivers/      Vendor SDK wrappers → ros2_control hardware interface
  safety/           Hardware e-stop, watchdog, safety PLC bridge
  mechanical/       Parametric enclosure, chassis, impact and stability package
  pcb/              Controller/power PCB architecture and KiCad engineering package
  manufacturing/    Assembly, test, quality, rework, EHS and release process
```

**Rule**: every adapter here must satisfy the same contract as its simulation counterpart.
`CanMotorAdapter` must emit the same `action_result` as the virtual device.
The verifier never knows which one is running.
