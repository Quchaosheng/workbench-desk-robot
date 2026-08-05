# safety

Hardware safety layer: e-stop, watchdog, safety PLC bridge.

This module has authority over motion regardless of software state. It is the
only place where a command issued by the robot runtime can be physically
overridden.

**Rule**: nothing in `services/` or `apps/` may bypass this layer.
Software safe-stop (from `firmware/virtual_mcu`) is not a substitute for
hardware e-stop. They are separate circuits.

Planned:
- USB e-stop button driver
- Safety relay bridge (Pilz PNOZmulti or similar)
- Watchdog heartbeat to motion controller
