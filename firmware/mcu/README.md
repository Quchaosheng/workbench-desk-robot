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

## Authority boundary

The C safety state machine under `core/` and its shared Host/QEMU transition
suite are authoritative for MCU safety behavior. The allocation-free Wire V1
codec under `core/frame_codec.[ch]`, its binary contract in
`docs/architecture/mcu-wire-v1.md`, and the shared Host/QEMU golden vectors are
authoritative for the Classic CAN payload encoding. `firmware/virtual_mcu/` is
retired as a safety reference and parity oracle. It remains only as a legacy
compatibility stub for earlier Python consumers and is not evidence of C
protocol, firmware, or physical safety behavior. Changes to that model require
a separate issue and must not silently be treated as C parity work.

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
make test-host-sanitize  # Host corpus under ASan and UBSan
make test-qemu   # fault suite in QEMU, what CI runs
```

## Status

The platform-independent C safety state machine is implemented by Issue #53.
Issue #54 adds the strict Classic CAN Wire V1 codec and shared Host/QEMU golden
vectors. The HAL CAN driver, watchdog timing path, command deduplication and
physical CAN validation remain separate follow-up tasks.
