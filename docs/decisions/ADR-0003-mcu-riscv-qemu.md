# ADR-0003: Safety MCU targets RISC-V, verified in QEMU

Status: accepted
Date: 2026-08-05

## Context

`firmware/virtual_mcu/` is a Python state machine. It is a useful contract stub
— Motion can build against it before any hardware exists — but it proves
nothing about firmware. A Python class asserting that it entered `safe_stop`
does not show that a cross-compiled binary does the same under a real timer
interrupt.

No MCU part had been chosen. Choosing one late means the whole firmware effort
lands in the last month, next to real-hardware bring-up, which is where
schedule risk is already highest.

## Decision

The safety MCU targets **RISC-V (rv32imac)**. The reference part is the
**CH32V307** (on-chip CAN, ~¥10, single-purpose enough for a safety element).
Firmware is verified in **QEMU in CI**, then on the board in P3.

Firmware splits into two layers:

```
firmware/mcu/
  core/           platform-independent C: state machine, frame codec,
                  watchdog, dedup, ring buffers.
                  No peripheral registers. No vendor headers.
  hal/qemu/       QEMU target, CTU CAN FD over PCI
  hal/ch32v307/   real board, CH32V307 CAN peripheral
  hal/host/       x86_64 build for fast logic tests
```

`core/` compiles to three targets from one source. Swapping the board means
writing a new `hal/`, not touching `core/`. That mirrors the project-wide rule
that implementations are replaceable and contracts are not.

## The QEMU limit, stated plainly

QEMU models **SJA1000** and **CTU CAN FD**, both over PCI. It does **not**
model the CH32V307 CAN peripheral. MCU-specific CAN models are added to QEMU
one part at a time (the STM32 bxCAN work is a patch series, not upstream).

So the split is:

| Proven in QEMU | Requires the board |
|---|---|
| State machine transitions | CH32V307 CAN register behaviour |
| Watchdog timing under a real timer interrupt | Bit timing (BRP/TSEG1/TSEG2/SJW) |
| Dedup across sequence wraparound | Error frames, bus-off recovery |
| Frame codec, ID partition enforcement | Electrical behaviour, EMI |
| Absence of malloc and FP instructions | Brownout, power-on reset |

This does not widen what we claim. The README already lists CAN electrical
behaviour and bus timing as not proven in simulation.

## Why RISC-V

- Royalty-free ISA, fully open toolchain — reproducibility is a project goal
- Mature upstream QEMU support for rv32
- Cheap real parts available now (CH32V307, ESP32-C6, GD32VF103)
- `core/` carries no vendor headers, so changing part means a new `hal/` only

CH32V307 over ESP32-C6 specifically: this is a safety element doing e-stop and
watchdog. WiFi and Bluetooth are attack surface on a component that must stay
independent of the network.

## Alternatives rejected

**Keep the Python model, test only on real hardware.** Pushes all firmware
risk into P3 alongside arm bring-up. Fault coverage would be unproven until
the last month.

**Write a QEMU device model for the CH32V307 CAN peripheral.** A project in
itself. Not worth it for v0.1.

**ARM + STM32.** The QEMU bxCAN support is a patch series, not upstream-
guaranteed. No advantage over RISC-V here, and it gives up the open-toolchain
argument.

## Cost

The MCU track grows from roughly one week (Python state machine) to about
2.5 weeks in P1: toolchain, startup code, QEMU harness, HAL split. P1 G-track
milestones move out by about a week.

CI gains a `mcu-qemu` job. It is cheap compared to Gazebo — no GPU, no display,
seconds per run.

## Consequences

- `firmware/virtual_mcu/` (Python) stays through P1 as the contract Motion
  builds against, and as the reference model for differential testing against
  the C core. It is **retired at the end of P1**, once `core/` passes the same
  fault suite. Two implementations of one state machine must not outlive P1.
- The `mcu_protocol` schema does not change. Same wire format, real
  implementation underneath.
- P3 payoff: the same `core/` binary passes the same fault suite in QEMU and on
  the board, with only `hal/` differing.

## References

- QEMU CAN emulation: https://www.qemu.org/docs/master/system/devices/can.html
- SocketCAN vcan: https://www.kernel.org/doc/html/latest/networking/can.html
- CH32V307 datasheet: https://www.wch-ic.com/products/CH32V307.html
