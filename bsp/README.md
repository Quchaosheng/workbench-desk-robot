# Robot BSP Workspace

This directory is the implementation home for the single Linux-board robot
BSP selected in `docs/architecture/robot-bsp-selection-v0.1.md`.

The current repository stage is logical freeze plus prototype selection. It is
not a bootable image and does not contain a target-board device tree yet.

Planned layout:

```text
bsp/
  board-manifest.yaml       selected board, SoC, power and interfaces
  linux/                     kernel config, patches and DTS once board is frozen
  boot/                      bootloader, boot arguments and recovery notes
  rootfs/                    reproducible rootfs manifest and system services
  firmware/                  versioned MCU images and compatibility manifest
  validation/                bring-up scripts and raw evidence references
```

Do not add pin numbers, IRQ numbers, register addresses or production power
limits until they are sourced from the selected carrier-board schematic and
vendor documentation.
