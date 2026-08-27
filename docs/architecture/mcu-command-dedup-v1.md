# MCU Command Deduplication V1

Issue #61 implements the ordinary-command replay boundary between the strict
Wire V1 decoder and the existing C safety state machine. It is allocation-free,
uses no platform APIs, and runs from the same source on Host and QEMU.

The frozen logical semantics remain in
`docs/architecture/mcu-protocol-v1.md`. This document records the bounded C
implementation choices; it does not add a field or change a Wire V1 value.

## Serial classification

Ordinary command IDs are `0..32767`. The complete low 15 bits are a serial
number modulo 32768. For a candidate and the most recently accepted serial:

```text
delta = (candidate - last_accepted) mod 32768
```

- `delta == 0` identifies the current retained command;
- `1 <= delta <= 16383` is serially new;
- `16384 <= delta <= 32767` is stale or ambiguous unless the exact ID is still
  in the configured replay window.

The implementation retains eight accepted ordinary-command records. This
covers the current host policy of one in-flight ordinary command plus its
bounded retry attempts. A retained earlier ID may replay while it remains in
that window. The ninth distinct accepted command overwrites the oldest slot;
later traffic for the evicted ID fails with `duplicate_frame`.

A half-range-new candidate takes precedence over an old cache entry with the
same numeric ID. If that forward transition crosses from a larger ID to a
smaller ID, the receiver clears every pre-wrap record before storing the new
one. Consequently `32766 -> 32767 -> 0 -> 1` advances normally, but a delayed
pre-wrap `32767` after `0` is stale and cannot replay an old ACK.

The host must not exceed the eight-record retention budget. Expanding the
in-flight policy requires an explicit review of this constant and the firmware
storage budget; it must not silently rely on the 16384 half range as a queue.

## New command and replay behavior

`mcu_command_dedup_receive()` accepts only a completely validated ordinary
`COMMAND`. The first serially new command dispatches exactly one event to the C
safety state machine:

| Opcode | Safety event | Successful mode |
| --- | --- | --- |
| `move` | `BEGIN_MOVE` | `moving` |
| `grip_open` | `BEGIN_MOVE` | `moving` |
| `grip_close` | `BEGIN_MOVE` | `moving` |
| `hold` | `BEGIN_HOLD` | `holding` |
| `heartbeat` | `HEARTBEAT` | current non-faulted mode |

The resulting ordinary ACK is cached even if the state machine rejects the
new event. That prevents the same ID from becoming executable later after a
state change. A repeated ID with the same opcode returns the cached
`result_code`, `fault_code`, and `device_mode` without dispatching that event
again.

`retry_count` is attempt metadata. The same count is an exact link replay; a
strictly greater count is a protocol retry and is echoed in the replayed ACK.
A decreasing count, including `255 -> 0`, is stale and rejected. Retry traffic
does not extend the software watchdog deadline.

A retained ID with a different opcode is a conflicting duplicate. Conflicts,
decreasing attempts, and unretained stale or ambiguous IDs:

1. do not dispatch the requested ordinary event;
2. enter or preserve the fail-closed MCU fault state;
3. return a rejected ordinary ACK with `duplicate_frame`; and
4. cannot refresh the software watchdog.

Malformed Wire V1 input is rejected before this API by the codec and does not
enter replay history. If an invalid wire object reaches this function, it
returns no record and does not mutate the state machine or dedup state.

## Session and reset boundary

Wire V1 has no boot/session epoch. `mcu_command_dedup_init()` therefore starts
with ordinary dispatch closed and empty history. The transport may call
`mcu_command_dedup_open_session(..., true)` only after it has discarded queued
pre-session traffic and established the trusted out-of-band startup gate. A
command received while closed produces no ACK and no state-machine event.

An active session cannot be reopened to erase history. The trusted transport
must explicitly close it, drain old traffic, and then open a fresh session.
MCU reboot follows the same closed initialization path.

An authorized safety-state reset is not a transport restart and does not clear
replay history. A duplicate command after reset still replays its historical
ACK without restarting motion. Neither serial wrap nor session establishment
is reset authorization.

## STOP independence

STOP uses the disjoint `32768..65535` partition and does not enter this replay
array. A valid STOP is routed directly to `mcu_watchdog_receive_stop()` before
ordinary correlation handling. It remains processable when the ordinary
window is full or the ordinary session gate is closed. Pending duplicate STOP
handling, retry monotonicity, ACK handoff, and timeout behavior remain owned by
`docs/architecture/mcu-watchdog-v1.md`.

The transport is the single writer of the dedup, state-machine, and watchdog
objects. If ingress can arrive from an ISR and a task, that owner must serialize
the calls and preserve STOP-first dispatch; this core does not hide a lock or
critical section inside platform-independent code.

## Resource and evidence boundary

The state contains exactly eight static entries and is compile-time bounded to
256 bytes. It has no allocator, floating point, vendor header, register access,
clock source, thread, or queue. Host and QEMU run the same exhaustive 15-bit
delta corpus plus retained replay, conflict, eviction, retry-wrap, session,
trusted-reset, and STOP-priority vectors.

These results prove platform-independent correlation and state-machine dispatch
behavior. They do not prove a CAN controller, STM32/CH32 HAL, physical bus,
actuator execution, motor stopping, electrical safety, or hard-real-time
latency. Those remain separate owner-gated evidence.
