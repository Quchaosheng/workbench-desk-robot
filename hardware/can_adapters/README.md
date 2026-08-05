# can_adapters

Bridges between physical CAN buses and the runtime.

Supported (planned):
- CANable 2.0 (USB, SocketCAN)
- PCAN-USB (Peak Systems)
- custom socketcan bring-up script

**What to implement**: `hardware_interface::SystemInterface` that opens a real
CAN socket instead of vcan. Output `action_result` with `dispatch_state` and
`device_state` separated — same contract as `firmware/virtual_mcu`.

Bring-up notes: `docs/hardware/can_bring_up.md`
