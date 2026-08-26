# Robot BSP V0.1 Freeze Package

Status: logical topology frozen; physical board and controller part selection
remains an implementation gate.

This document freezes the logical ownership and safety boundaries for the robot
board-support package. The selected quantity is **one Linux development board
and six controller domains per robot**: two robot-owned MCUs and four arm/tool
module controller domains. It does not claim that a physical board, kernel port,
device tree, or production safety approval exists. Exact SoC, kernel release,
CAN controller, pin numbers, IRQ numbers, and electrical ratings remain open
until the board selection gate is signed.

The quantity decision is intentionally independent of vendor part selection:
one Linux board is the single high-level compute and gateway domain, while the
six controller domains provide real-time ownership and safety isolation. Adding a
second Linux board or a seventh controller domain requires a new architecture review and
cannot happen implicitly in a BSP implementation PR.

## 1. System topology

```text
                         Linux development board
          ROS 2 / planning / perception / navigation / services
          device management / logs / update / diagnostics
             |       |        |        |        |
          CAN-FD   Ethernet   USB     UART    debug console
             |
       isolated CAN backbone (CAN0, two physical termination points)
        |             |              |              |
   MCU-BASE    ARM-L CTRL    ARM-R CTRL    TOOL-L CTRL    TOOL-R CTRL    MCU-SAFETY
   chassis     left 7-axis   right 7-axis  left end tool  right end tool  E-stop/watchdog/
   drive/lift  module ctrl   module ctrl   module ctrl    module ctrl     safe enable

  Power path: battery -> protected power entry -> Linux and MCU rails.
  Safety path: E-stop -> MCU-SAFETY -> independent drive/arm enables.
  Linux commands are requests; they cannot create a safety permissive.
```

The baseline uses one Linux board and six controller domains. The lift is owned
by `MCU-BASE` for V0.1. Arm and tool domains may be vendor controller boards or
local MCUs, but each is independently resettable and addressable. A separate
`MCU-LIFT` is not part of V0.1.

## 2. MCU ownership

| Node | Required responsibility | Must not own |
|---|---|---|
| `MCU-BASE` | traction motors, wheel encoders, chassis odometry, lift motion and limits | E-stop decision or Linux application state |
| `ARM-L-CTRL` | left seven-axis arm servo/control interface | right arm or global safety latch |
| `ARM-R-CTRL` | right seven-axis arm servo/control interface | left arm or global safety latch |
| `TOOL-L-CTRL` | left end-effector control, limits and telemetry | arm trajectory planning or global safety latch |
| `TOOL-R-CTRL` | right end-effector control, limits and telemetry | arm trajectory planning or global safety latch |
| `MCU-SAFETY` | dual-channel E-stop, safe enables, watchdog, fault latch and safety inputs | trajectory planning, vision, ordinary telemetry aggregation |

Each domain has an independent heartbeat, boot identifier, fault state and reset
domain. Loss of one motion node must not silently clear the safety latch or
enable another motion node.

## 3. Linux board interface allocation

These are logical allocations. Numeric pins and SoC IRQs are intentionally
unassigned until the schematic and device-tree review.

| Logical resource | Linux name | Owner | IRQ/DMA rule | Freeze evidence |
|---|---|---|---|---|
| Isolated CAN backbone | `can0` | all MCU nodes | controller IRQ is threaded/NAPI-safe; DMA only if controller requires it | controller data sheet, bus timing and termination review |
| Service Ethernet | `eth0` | Linux services/update | use SoC MAC IRQ and documented PHY reset GPIO | PHY address, reset timing and link test |
| USB host | `usb0` | cameras, storage, service tools | xHCI IRQ owned by kernel; no safety dependency | power budget and hot-plug test |
| MCU service UART | `ttyS-mcu` | Linux to recovery console | RX DMA optional; wakeup IRQ must be documented | baud, level shifting and recovery transcript |
| Debug console UART | `ttyS-debug` | boot and field recovery | console IRQ must not share an unacknowledged safety IRQ | boot log and recovery procedure |
| Board management I2C | `i2c-bmc` | PMIC, thermal and fan devices | controller IRQ only for alert GPIO; bus recovery defined | address map and stuck-bus test |
| Expansion SPI | `spi-exp` | IMU or future sensor | per-device CS; threaded IRQ for data-ready GPIO | mode, frequency and data-ready ownership |
| Non-safety GPIO | `gpio-exp` | LEDs, presence and service inputs | GPIO IRQ must identify edge and debounce policy | pinmux and debounce review |
| Linux watchdog | `watchdog0` | Linux health supervision | timeout and pretimeout IRQ are documented; cannot replace MCU-SAFETY | reboot and boot-status evidence |

No Linux GPIO, CAN, UART, SPI or watchdog resource may be described as a
replacement for the independent `MCU-SAFETY` path.

## 4. Power and safety boundaries

1. Battery input enters a protected power stage before Linux or motion loads.
2. Linux power is separately fused from motion power and may be restarted
   without re-enabling actuators.
3. Each motion MCU has a defined brownout and reset state: outputs disabled,
   brakes applied where applicable, and a fault reported after reboot.
4. `MCU-SAFETY` controls the hardware enable chain. A valid Linux command can
   request motion but cannot close that chain.
5. E-stop, channel discrepancy, watchdog expiry, driver fault and lost MCU
   heartbeat all produce a latched inhibit until the documented manual reset.
6. CAN isolation, shield termination and chassis bonding are fixed by the
   electrical design review; software must not infer them.

## 5. V0.1 node and CAN allocation

| Node | ID | CAN role | Reset domain |
|---|---:|---|---|
| Linux gateway | `0x01` | host gateway and diagnostics; never a safety authority | Linux board |
| `MCU-BASE` | `0x10` | traction, encoders, lift and chassis telemetry | base motion |
| `ARM-L-CTRL` | `0x11` | left seven-axis arm control | left arm |
| `ARM-R-CTRL` | `0x12` | right seven-axis arm control | right arm |
| `TOOL-L-CTRL` | `0x13` | left end-effector control | left tool |
| `TOOL-R-CTRL` | `0x14` | right end-effector control | right tool |
| `MCU-SAFETY` | `0x1F` | safety state and inhibit diagnostics | independent safety |

These node IDs are logical V0.1 identifiers, not final arbitration IDs. The
reserved `0x1F` safety node must retain the highest protocol priority for STOP
and fault traffic. The complete arbitration map, bitrate and physical CAN
controller remain implementation gates.

## 6. Multi-node CAN contract to add before BSP implementation

The existing MCU Wire V1 defines frame semantics but does not freeze a complete
multi-node address plan. BSP V0.1 therefore requires:

- a unique node ID for each controller domain and a reserved Linux gateway ID;
- priority and identifier allocation for STOP, command, acknowledgement,
  telemetry and fault frames;
- independent sequence spaces and boot IDs per node;
- discovery, heartbeat timeout, bus-off recovery and duplicate-command rules;
- a matrix describing the safe result when each node is offline or rebooting.

`kernel/wbcan` remains a virtual regression device. It cannot be used as proof
of physical CAN throughput, latency, EMC, or bus recovery.

## 7. Execution stages after quantity freeze

1. **BSP-1 board selection:** select one Linux board and record SoC, memory,
   storage, power input, CAN interface, kernel baseline and boot media.
2. **BSP-2 controller selection:** select the `MCU-BASE` and `MCU-SAFETY`
   parts, then record vendor arm/tool controller interfaces, clocks, flash/RAM,
   CAN peripheral, reset, programming and watchdog resources.
3. **BSP-3 electrical and device tree:** freeze schematic net names, pinctrl,
   clocks, regulators, GPIO polarity, IRQ ownership and CAN termination.
4. **BSP-4 boot image:** produce reproducible bootloader, kernel, DTB, rootfs,
   firmware bundle and recovery image for the single Linux board.
5. **BSP-5 hardware bring-up:** prove boot, CAN discovery, six heartbeats,
   STOP, MCU reset, Linux restart and independent E-stop on real hardware.

## 8. Freeze gates

The package is ready to move from proposal to implementation only when all of
the following have an owner and evidence reference:

- Linux board model, SoC, boot media and target Linux kernel version;
- CAN controller/PHY model, oscillator, bitrate and termination;
- MCU part numbers, clock rates, flash/RAM, reset domains and programming path;
- schematic net names, connector pinout, power rails and fuse limits;
- device-tree resource map, pinctrl groups, GPIO polarity and IRQ ownership;
- MCU node-ID and CAN arbitration plan;
- E-stop and safe-enable truth table reviewed by the safety owner;
- reproducible cross-compile, image assembly and recovery instructions.

Until the physical selection and bring-up gates close, the BSP status is
`LOGICAL_TOPOLOGY_FROZEN_PHYSICAL_BRINGUP_PENDING`.
