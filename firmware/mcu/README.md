# Safety MCU firmware

Target: RISC-V rv32imac. Reference part: CH32V307.
Decision and rationale: `docs/decisions/ADR-0003-mcu-riscv-qemu.md`.

## Layout

```
core/           platform-independent C. State machine, frame codec,
                watchdog, dedup, ring buffers.
                No peripheral registers. No vendor headers.
hal/qemu/       QEMU target, CTU CAN FD over PCI. Used by CI.
hal/ch32v307/   real board, CH32V307 CAN peripheral. P3.
hal/host/       x86_64 build, for fast logic tests.
tests/          shared test suite, runs against all three targets.
```

`core/` compiles to three targets from one source. Changing the board means
writing a new `hal/`, not touching `core/`.

## The one rule

`core/` must not include a vendor or platform header. Any register access
belongs in `hal/`. An `#ifdef CH32V307` inside `core/` means the boundary has
been violated.

## What QEMU proves and doesn't

QEMU models SJA1000 and CTU CAN FD, not the CH32V307 CAN peripheral.

| Proven in QEMU | Requires the board |
|---|---|
| State machine transitions | CH32V307 CAN register behaviour |
| Watchdog timing under a real timer interrupt | Bit timing (BRP/TSEG1/TSEG2/SJW) |
| Dedup across sequence wraparound | Error frames, bus-off recovery |
| Frame codec, ID partition enforcement | Electrical behaviour, EMI |
| Absence of malloc and FP instructions | Brownout, power-on reset |

## Build

```bash
make host        # x86_64 library for fast tests
make qemu        # rv32imac ELF for QEMU
make board       # rv32imac ELF to flash (P3)

make test-host   # logic tests, seconds
make test-qemu   # fault suite in QEMU, what CI runs
```

## Status

Skeleton only. First task is FW1 (toolchain and build system). Until
`core/*.c` exists, the `mcu-qemu` CI job reports "not implemented yet" and
passes — it must not report green as if the suite had run.
