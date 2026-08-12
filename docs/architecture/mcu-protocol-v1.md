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
modify firmware or robot control.

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

`frame_id` is evidence identity. `command_id` is command correlation. A new
retry keeps the same command semantics and increments `retry_count`; it does not
turn a write into confirmation. Telemetry has no command correlation and uses
`sequence_no` instead.

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
use them as command IDs. Retry counts are `0..255`.

Ordinary opcodes are `move`, `grip_open`, `grip_close`, `hold` and `heartbeat`.
`stop` is valid only in `stop` and `stop_ack`.

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
| `duplicate_frame` | Failed ordinary `ack` | The ordinary command ID was already observed and was rejected as a duplicate. The receiver must not execute it again. |
| `watchdog_expired` | Fault telemetry | The MCU watchdog deadline expired and the device entered faulted mode. |
| `malformed_frame` | Failed ordinary `ack` | The MCU parsed enough correlation data to reject an otherwise invalid ordinary frame. No requested action may be assumed. |

`ack_timeout` and `stop_timeout` describe the absence of a frame, so they are in
the frozen fault vocabulary but cannot appear inside a valid MCU-originated
frame. Consumers synthesize them only after their configured host deadline. The
deadline values themselves are deployment policy, not part of protocol v1.0.

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
