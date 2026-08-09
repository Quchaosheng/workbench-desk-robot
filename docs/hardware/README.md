# docs/hardware

Hardware bring-up notes and integration guides.

```
hardware/
  can_bring_up.md        SocketCAN setup, USB-CAN adapters, bitrate config
  camera_calibration.md  intrinsic + extrinsic calibration workflow
  cross_compile.md       cross-compilation for ARM64 boards (RDK X5, etc.)
  safety_wiring.md       e-stop circuit, watchdog, safety relay
```

General rule: all bring-up steps are scripted where possible. If a step
requires manual action (physical wiring, screwdriver), it is documented
with a photo reference and a verifiable outcome (e.g. "voltage reading X").

## Preflight

The software-only preflight never sends a CAN, motor, or emergency-stop command:

```bash
python tools/scripts/hardware_preflight.py --output runs/hardware/preflight.json
```

It reports `not_ready` until Linux, the configured CAN interface, camera device,
and an operator-created emergency-stop marker are all present. A `not_ready`
result is an explicit block, not a request to continue with simulated hardware.
