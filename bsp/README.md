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
  sensors/                   selected sensor interfaces and integration boundaries
  validation/                bring-up scripts and raw evidence references
```

Run `python bsp/validation/validate_manifests.py` before changing a board,
controller or firmware manifest. The validator checks domain identity and
keeps physical bring-up results fail-closed until evidence is attached.

The public candidate baseline and source links are recorded in
[`public-candidate-selection.md`](public-candidate-selection.md). It makes the
next purchase and integration decisions concrete without treating public
documentation as supplier approval or physical evidence.

The prototype camera baseline is one head-mounted Intel RealSense D435 over
USB 3. Linux uses the standard `uvcvideo`/V4L2 path, with `librealsense2` and
the ROS 2 `realsense2_camera` package above the kernel. See
`sensors/camera-head.yaml` and
`../docs/architecture/robot-bsp-camera-v0.1.md`. Exact JetPack-compatible
package versions, serial identity, stream modes, calibration and physical
evidence remain open bring-up gates; wrist cameras are deferred until measured
occlusion shows that the single head camera is insufficient.

Do not add pin numbers, IRQ numbers, register addresses or production power
limits until they are sourced from the selected carrier-board schematic and
vendor documentation.
