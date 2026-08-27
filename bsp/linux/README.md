# Linux BSP Inputs

The selected prototype target is Jetson Orin Nano Super 8GB. This directory
will hold the target kernel configuration, device-tree sources, patches and
build metadata after the carrier board is confirmed.

Required files before a physical image is called reproducible:

- `kernel-config` with the exact JetPack/L4T kernel release;
- device-tree source for power, pinctrl, CAN, UART, I2C, SPI, USB and Ethernet;
- patch manifest with upstream base and checksums;
- compiler/toolchain manifest;
- build command and output hashes.

Until the carrier schematic supplies pin and IRQ numbers, no DTS node is
allowed to claim a physical GPIO, clock, regulator or CAN controller.
