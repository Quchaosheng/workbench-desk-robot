# MCU logical-frame protocol v1.0

Status: **frozen logical contract** for G1 / Issue #44.

The normative machine-readable sources are
`interfaces/json_schema/mcu_protocol.schema.json` and the exported
`workbench_contracts.McuFrame` Pydantic model. This document explains their
meaning. If an implementation cannot satisfy both sources, it must reject the
frame.

## Boundary

Version 1.0 freezes the transport-independent logical frames exchanged between
the host runtime and the MCU adapter. It does **not** freeze a CAN identifier,
byte order, DLC, checksum or mapping into the eight bytes of
`firmware/mcu/core/hal.h::hal_can_frame`. That binary encoding requires a
separate firmware-owned contract and must not be inferred from this JSON shape.

The existing Virtual MCU and C HAL are affected producers/consumers and must be
updated by their owners before they claim v1.0 wire compatibility. G1 does not
modify firmware or robot control. The logical semantics in this document are
the stable input to the C safety state machine (#53), strict frame codec (#54),
watchdog/STOP timing path (#60), and deduplication implementation (#61).

## Common invariants

Every frame carries:

- `protocol_version`: exactly `"1.0"`;
- `frame_id`: a unique diagnostic identifier beginning with `mcu-frame-`;
- `frame_kind`: one of the five shapes below;
- `sent_at_us`: an unsigned 64-bit monotonic timestamp in microseconds;
- `clock_id`: exactly `"monotonic"`.

Unknown fields, missing required fields, JSON booleans where integers are
required, out-of-range integers, wall-clock timestamps and unknown enum values
are invalid. Producers must not emit them. Consumers must reject the complete
frame without applying a command or changing confirmed state.

The Schema declares the obsolete `sent_at` name only so the repository's
limited object-schema compiler can inspect the field table. Every v1.0 frame
branch explicitly rejects it; it is not a protocol field. `sent_at_us` is the
only valid timestamp field. The compiler-generated flat model is not the
normative MCU validator; consumers use the full JSON Schema or exported
`McuFrame` model.

`frame_id` is evidence identity. `command_id` is command correlation. A
deliberate retry keeps the same command semantics and `command_id`, increments
`retry_count`, and uses a new `frame_id` and send timestamp. A link-level copy
may repeat the same retry count. Neither case turns a write into confirmation.
Telemetry has no command correlation and uses `sequence_no` instead.

## Frame shapes

| Kind | Direction | Required kind-specific fields | Meaning |
| --- | --- | --- | --- |
| `command` | host to MCU | `command_id`, ordinary `opcode`, `retry_count` | Request an ordinary operation. Receipt or transport write is not completion. |
| `ack` | MCU to host | command fields plus `result_code`, `fault_code`, `device_mode` | Deterministic response to one ordinary command. |
| `telemetry` | MCU to host | `sequence_no`, `fault_code`, `device_mode` | Unsolicited state/fault snapshot. It never confirms a command. |
| `stop` | host to MCU | stop-range `command_id`, `opcode=stop`, `retry_count` | Request safe stop using a disjoint identifier range. |
| `stop_ack` | MCU to host | stop fields plus `result_code`, `fault_code`, `device_mode` | Response to one stop. Only a successful `stop_ack` confirms stopped state. |

Ordinary `command` and `ack` identifiers are `0..32767`. `stop` and
`stop_ack` identifiers are `32768..65535`. This partition prevents an ordinary
ack from being mistaken for a stop acknowledgement. Telemetry sequence numbers
are unsigned 32-bit values (`0..4294967295`) and may wrap; consumers must not
use them as command IDs. For telemetry ordering, receivers use
`delta = (candidate - last_accepted) mod 4294967296`: zero is duplicate,
`1..2147483647` is newer, and `2147483648..4294967295` is stale or ambiguous.
Telemetry is never command confirmation regardless of ordering. Retry counts
are `0..255`.

Ordinary opcodes are `move`, `grip_open`, `grip_close`, `hold` and `heartbeat`.
`stop` is valid only in `stop` and `stop_ack`.

## Correlation, retry and wrap semantics

The command identifier is an unsigned 16-bit value whose high bit is the
command class. The low 15 bits form a serial number modulo 32768. Ordinary and
STOP serial histories are independent; ordinary traffic can never consume or
block the STOP history.

For a new ordinary logical request, the host advances the low 15-bit serial.
For a retry, it keeps the same `command_id` and opcode. Command semantics are
the tuple (`protocol_version`, `command_id`, `opcode`); `frame_id`,
`retry_count`, and `sent_at_us` are attempt metadata and are not part of that
tuple. The MCU classifies an ordinary candidate relative to the last accepted
serial using
`delta = (candidate - last_accepted) mod 32768`:

- `delta=0` is a duplicate or retry of the current serial;
- `1..16383` is newer, including the wrap from 32767 to 0;
- `16384..32767` is stale or ambiguous and fails closed.

Normative boundary vectors are: `(last, candidate) = (32766, 32767)`,
`(32767, 0)`, `(0, 1)`, and `(0, 16383)` are newer; `(0, 0)` is duplicate;
`(0, 16384)`, `(0, 32767)`, and `(1, 0)` are stale or ambiguous.

The host must keep the number of outstanding, skipped and retried ordinary IDs
below the 16384 half-range. A receiver must retain a bounded correlation record
for every ID that can still be retried under its configured in-flight and retry
budgets. A retry matching the retained command semantics returns the original
`result_code`, `fault_code` and `device_mode`; it must not execute side effects
again. A repeated response may use a new `frame_id` and `sent_at_us`, and its
`retry_count` echoes the received request. An already retained ID with different
command semantics, or a stale/out-of-window ordinary ID, returns a failed
ordinary ack with `duplicate_frame` and does not execute.

A structurally valid STOP is accepted for safety processing from every state
before correlation-history handling and cancels or prevents ordinary command
execution. If safe stopped state is achieved, a matching STOP retry returns the
same successful result without repeating side effects. If it cannot be
achieved, the MCU emits the failed `stop_ack` defined below and remains faulted.
The ordinary-command replay window must never suppress STOP processing.

Protocol v1.0 has no on-wire boot/session epoch. After either endpoint restarts,
normal command dispatch must remain disabled until the owning transport has
discarded queued pre-restart traffic and established a fresh trusted session by
an out-of-band startup gate. The first ordinary serial is accepted only after
that gate. A restart or ID wrap is not reset authorization.

## Result semantics

`result_code` is deliberately closed to two values:

- `0`: accepted/successful response;
- `1`: rejected/failed response.

A successful ordinary `ack` requires `fault_code=none` and a non-faulted mode.
A failed ordinary `ack` requires `device_mode=faulted` and exactly one of
`duplicate_frame` or `malformed_frame`.

A successful `stop_ack` requires `fault_code=none` and
`device_mode=stopped`. A failed `stop_ack` requires
`fault_code=stop_rejected` and `device_mode=faulted`. No other combination is
valid. In particular, a `stop` write, telemetry saying `stopped`, an ordinary
ack, or absence of an error is not stop confirmation.

## Telemetry semantics

Device modes are `idle`, `moving`, `holding`, `stopped` and `faulted`. Healthy
telemetry has `fault_code=none` and any non-faulted mode. Fault telemetry has
`device_mode=faulted` and exactly `link_lost` or `watchdog_expired`.

Telemetry is evidence about the current device snapshot only. It cannot be used
to infer that a particular command ID was accepted.

## Fault-code registry

| Code | Authority / occurrence | Deterministic meaning and required response |
| --- | --- | --- |
| `none` | MCU frame | No fault is asserted by this frame. It does not by itself confirm a command. |
| `ack_timeout` | Host diagnostic; no MCU frame arrived | No matching ordinary ack was received before the configured deadline. The command remains unconfirmed; enter the host recovery policy. |
| `stop_timeout` | Host diagnostic; no MCU frame arrived | No matching successful stop_ack was received before the stop deadline. Stopped state is unconfirmed; escalate via the safety policy. |
| `stop_rejected` | Failed `stop_ack` | The MCU explicitly rejected or could not complete the stop request. The device is faulted; never report stopped confirmation. |
| `link_lost` | Fault telemetry | The MCU detected loss of its required control/heartbeat link and entered faulted mode. |
| `duplicate_frame` | Failed ordinary `ack` | The ordinary command ID is stale/out of window or conflicts with retained command semantics. The receiver must not execute it. An exact semantic retry returns the retained original result and is not this fault. |
| `watchdog_expired` | Fault telemetry | The MCU watchdog deadline expired and the device entered faulted mode. |
| `malformed_frame` | Failed ordinary `ack` | The MCU parsed enough correlation data to reject an otherwise invalid ordinary frame. No requested action may be assumed. |

`ack_timeout` and `stop_timeout` describe the absence of a frame, so they are in
the frozen fault vocabulary but cannot appear inside a valid MCU-originated
frame. Consumers synthesize them only after their configured host deadline. The
deadline values themselves are deployment policy, not part of protocol v1.0.

## Time and deadline semantics

`sent_at_us` is read from the sender's local monotonic clock and is scoped to
that sender's current boot. It may restart at zero after reboot. Host and MCU
clock origins are not synchronized, so a consumer must not subtract timestamps
from different senders or use `sent_at_us` alone as freshness, timeout or replay
evidence. Receivers record local monotonic arrival time for those decisions.

The host starts an ordinary acknowledgement deadline from its local successful
transport dispatch and starts the STOP deadline from local STOP dispatch. The
MCU measures its STOP-response bound from local receipt of a completely valid
STOP to handing the correlated `stop_ack` to its transport. Transport dispatch
or queueing is not physical actuation evidence, and the numerical deadline
values remain controlled implementation constants owned by #55 and #60.

Only a completely valid, serially new ordinary command (including a heartbeat)
is eligible to refresh the MCU software link watchdog while execution is
allowed. Malformed, conflicting, duplicate, retry and stale frames do not
refresh it and therefore cannot keep execution alive indefinitely. STOP is
processed for safety but does not extend an execution watchdog deadline.

## Reset authority

Protocol v1.0 deliberately does not define a reset frame or reset opcode.
Ordinary commands, heartbeat, telemetry, STOP, acknowledgement receipt and a
transport reconnect cannot clear `stopped` or `faulted` state or authorize
motion.

The platform-independent MCU safety state machine may accept a separate trusted
reset event only after the live stop/watchdog/fault cause is cleared and the
owning safety control path has established operator authorization where site
policy requires it. That control path and its authentication are outside this
logical-frame protocol; a caller must not derive reset authority solely from any
v1.0 frame. An accepted reset enters `idle`, never an executing mode, and any
later motion requires a new ordinary command. Power cycling starts a new
non-executing session and does not restore pending motion. Adding an on-wire
reset operation requires a new protocol version and the interface-owner
approval process.

## Fail-closed handling

Consumers validate the entire frame before dispatch or state mutation. On any
validation failure they must:

1. discard the frame as a protocol message;
2. not execute a command or mark an action/stop confirmed;
3. retain the raw input only as bounded diagnostic evidence;
4. emit the owning subsystem's malformed-input diagnostic.

The committed `interfaces/examples/mcu-frame-stop-ack.json` is the canonical
successful stop acknowledgement. Contract tests validate it and a shared valid
and invalid corpus through both Draft 2020-12 JSON Schema and Pydantic.
