# Safety MCU firmware

Target: RISC-V rv32imac. Reference part: CH32V307.
Decision and rationale: `docs/decisions/ADR-0003-mcu-riscv-qemu.md`.

## Layout

```
core/           platform-independent C. State machine, frame codec,
                watchdog timing, dedup, ring buffers.
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
vectors. Issue #60 adds the allocation-free heartbeat watchdog, bounded STOP
acknowledgement timing, fake-clock tests and QEMU machine-timer/watchdog
evidence. The HAL CAN driver, command deduplication and physical CAN validation
remain separate follow-up tasks.

## Timing safety path

`core/watchdog.[ch]` owns the timing state but not timer or watchdog registers.
Only a complete, valid and serially new ordinary frame may refresh the
software link watchdog. Malformed, retry, duplicate, stale and STOP traffic do
not extend the execution deadline. A missed deadline enters the existing
latched `FAULT/watchdog_expired` state and emits one telemetry record.

A valid STOP immediately transitions the state machine to `SAFE_STOP` and
creates a correlated `STOP_ACK` handoff record. The transport must confirm the
handoff before the controlled deadline; otherwise the core emits one local
`STOP_TIMEOUT` outcome and never claims stopped confirmation. The exact
constants and clock-wrap rules are documented in
`docs/architecture/mcu-watchdog-v1.md`.

While the STOP handoff is pending, an equal `retry_count` is an exact
link-level replay and a strictly greater count is a protocol-level retry.
Decreasing or wrapped retry counts are stale and rejected without changing the
pending ACK correlation.
