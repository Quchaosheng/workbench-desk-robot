# Robot BSP V0.1 Freeze Package

Status: architecture proposal pending board and controller selection.

This document freezes the logical ownership and safety boundaries for the robot
board-support package. It does not claim that a physical board, kernel port,
device tree, or production safety approval exists. Exact SoC, kernel release,
CAN controller, pin numbers, IRQ numbers, and electrical ratings remain open
until the board selection gate is signed.

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
   MCU-BASE       MCU-ARM-L      MCU-ARM-R      MCU-SAFETY
   chassis        left 7-axis    right 7-axis   E-stop/watchdog/
   drive/lift     arm + tool     arm + tool      safe enable

  Power path: battery -> protected power entry -> Linux and MCU rails.
  Safety path: E-stop -> MCU-SAFETY -> independent drive/arm enables.
  Linux commands are requests; they cannot create a safety permissive.
```

The baseline uses four MCUs. The lift is owned by `MCU-BASE` for V0.1. A
separate `MCU-LIFT` is allowed only if the selected lift controller requires a
different real-time rate, isolation boundary, or safety certification package.

## 2. MCU ownership

| Node | Required responsibility | Must not own |
|---|---|---|
| `MCU-BASE` | traction motors, wheel encoders, chassis odometry, lift motion and limits | E-stop decision or Linux application state |
| `MCU-ARM-L` | left seven-axis arm, left tool, local limits and servo loop | right arm or global safety latch |
| `MCU-ARM-R` | right seven-axis arm, right tool, local limits and servo loop | left arm or global safety latch |
| `MCU-SAFETY` | dual-channel E-stop, safe enables, watchdog, fault latch and safety inputs | trajectory planning, vision, ordinary telemetry aggregation |

Each node has an independent heartbeat, boot identifier, fault state and reset
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

## 5. Multi-node CAN contract to add before BSP implementation

The existing MCU Wire V1 defines frame semantics but does not freeze a complete
multi-node address plan. BSP V0.1 therefore requires:

- a unique node ID for each MCU and a reserved Linux gateway ID;
- priority and identifier allocation for STOP, command, acknowledgement,
  telemetry and fault frames;
- independent sequence spaces and boot IDs per node;
- discovery, heartbeat timeout, bus-off recovery and duplicate-command rules;
- a matrix describing the safe result when each node is offline or rebooting.

`kernel/wbcan` remains a virtual regression device. It cannot be used as proof
of physical CAN throughput, latency, EMC, or bus recovery.

## 6. Freeze gates

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

Until these gates close, the BSP status is `PROPOSAL_NOT_READY_FOR_PHYSICAL_BRINGUP`.
