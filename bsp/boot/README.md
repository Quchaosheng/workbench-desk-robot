# BSP Boot and Recovery Checklist

This checklist is a gate for the selected Jetson prototype board. Values that
depend on the final carrier board remain `TBD` until sourced from its vendor
manual and schematic.

## Required records

- JetPack/L4T and Linux kernel release, compiler version and configuration hash
- boot media image hash, UEFI/bootloader configuration and kernel command line
- device-tree source and compiled DTB hash
- rootfs manifest, systemd unit list and firmware bundle hash
- recovery image, rollback procedure and serial-console transcript

The machine-readable source of truth is `bsp/image/build-inputs.yaml`. Run
`python bsp/validation/validate_image_inputs.py` before attempting a build.
The committed manifest deliberately remains `inputs_unresolved` and
`build_ready: false` until every version, source, repository input and digest
is frozen. Generated hashes never prove that the image booted on hardware.

## Bring-up order

1. Boot with motion power isolated; verify console, storage, Ethernet and USB.
2. Verify Linux watchdog and reboot recovery without enabling actuators.
3. Bring up `can0` with no motion load; record controller, bitrate and error
   counters once the physical adapter is selected.
4. Discover `MCU-SAFETY` first and prove the hardware inhibit remains active.
5. Discover `MCU-BASE`, `ARM-L-CTRL`, `ARM-R-CTRL`, `TOOL-L-CTRL` and
   `TOOL-R-CTRL`; record six heartbeats and boot IDs.
6. Exercise STOP, node reset, Linux restart, bus-off recovery and manual reset
   under guarded conditions.

No actuator enable, physical success, EMC pass or hard-real-time result may be
claimed from a host-only or `wbcan` run.
