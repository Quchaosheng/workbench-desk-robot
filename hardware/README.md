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
  procurement/      Controlled BOM, quote requests, supplier review and PO gates
  qa/               Inspection standards, FMEA, AQL and compliance evidence gates
  validation/       SIM2REAL, diagnostics, fault injection and field acceptance
```

**Rule**: every adapter here must satisfy the same contract as its simulation counterpart.
`CanMotorAdapter` must emit the same `action_result` as the virtual device.
The verifier never knows which one is running.

## Release truth

The engineering packages are reproducible and testable, but they do not imply a
physical build, supplier quote, laboratory certification, or field run. The
procurement, QA, and validation reports deliberately keep those external gates
blocked until dated evidence is attached.
