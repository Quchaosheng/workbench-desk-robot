# MCU Watchdog and STOP Timing V1

Issue #60 owns the platform-independent timing safety path that sits above the
Wire V1 codec and beside the C safety state machine. It turns missing valid
control activity and an unconfirmed STOP acknowledgement into deterministic
safe outcomes without claiming a physical board timing result.

## Controlled constants

The current implementation keeps all deployment-sensitive values in
`firmware/mcu/core/watchdog.h`:

| Constant | Value | Meaning |
| --- | ---: | --- |
| `MCU_HEARTBEAT_PERIOD_US` | 50,000 us | one-shot timer re-arm period |
| `MCU_SOFTWARE_WATCHDOG_TIMEOUT_US` | 150,000 us | local link deadline after accepted activity |
| `MCU_STOP_ACK_DEADLINE_US` | 10,000 us | bound from valid STOP receipt to transport handoff confirmation |
| `MCU_HARDWARE_WATCHDOG_PERIOD_MS` | 500 ms | HAL hardware-watchdog configuration |

These are implementation constants for deterministic Host/QEMU evidence. They
are not CH32V307 interrupt-latency, motor-stop, electrical-bus or physical
E-stop measurements.

## Software link watchdog

The transport/parser boundary must validate a complete frame and decide that
its ordinary command serial is new before calling
`mcu_watchdog_note_activity(..., MCU_WATCHDOG_ACTIVITY_VALID_NEW, ...)`.
Only that explicit activity arms or refreshes the local deadline. Retries,
duplicates, stale/out-of-window frames, malformed input and STOP never refresh
an execution deadline.

The deadline is an absolute `uint64_t` monotonic timestamp. The core compares
timestamps using the unsigned half-range rule, so a deadline crossing
`UINT64_MAX` remains deterministic. The implementation assumes, as required by
the contract, that any one timing window is shorter than half the counter
range.

When the deadline is reached while the state machine is `EXECUTING`, the core:

1. dispatches `MCU_EVENT_WATCHDOG_EXPIRED`;
2. enters the latched `FAULT` / `watchdog_expired` state;
3. disables further link-deadline refresh; and
4. publishes exactly one correlated telemetry record with a monotonically
   assigned telemetry sequence.

Further polls do not emit another record. Ordinary activity cannot revive the
state. Reset still requires the existing trusted authorization and an
independent cause-cleared gate.

## STOP acknowledgement timing

For a completely valid STOP, the core dispatches the state-machine STOP event
first, disables the software link deadline, stores the STOP command ID and
attempt metadata, and creates a correlated `STOP_ACK` record immediately. The
record is eligible for transport handoff until the inclusive
`MCU_STOP_ACK_DEADLINE_US` deadline.

The transport-facing adapter confirms the handoff with
`mcu_watchdog_confirm_stop_ack()`. The command ID and retry count of the most
recently emitted ACK must match the pending slot. A confirmation at the exact
deadline is accepted; a late confirmation is rejected.

If the handoff is not confirmed after the deadline, the pending slot is closed
and exactly one local `STOP_TIMEOUT` record is published. This is a local
absence-of-confirmation diagnostic, not a valid MCU Wire V1 fault frame and
never evidence that stopped confirmation was received. The safe state remains
active and trusted reset cannot clear the timing cause until the owner marks it
cleared.

An exact link-level STOP retry while the pending slot is live replays the cached
original STOP ACK record, including its observed timestamp, retry count, wire
result, fault and device mode, and does not extend the deadline. A
protocol-level retry with the same STOP command ID and a different
`retry_count` matches the same command semantics, emits a new observation that
echoes the received `retry_count`, and preserves the original wire result,
fault and device mode. Neither form repeats the STOP side effect or extends the
deadline; the most recently emitted retry count is the one used for transport
handoff confirmation and timeout correlation. Both replays remain unchanged in
their semantic fields if the state machine enters a fault after the first ACK
was created. A different pending STOP is rejected by the bounded single-slot
implementation; retry deduplication and multi-command windows remain separate
work.

## Hardware watchdog and HAL boundary

The core never touches timer or watchdog registers. It asks the HAL for:

- monotonic microseconds;
- one-shot timer arm/disarm and interrupt enable;
- hardware watchdog start/feed; and
- bounded Host/QEMU evidence counters.

The QEMU HAL maps time to the virt machine CLINT `mtime`, dispatches a real
machine-timer interrupt through `crt0.S`, and models the hardware watchdog as a
finite deadline. The timer callback runs the same `mcu_watchdog_poll()` source
as Host and feeds the modeled hardware watchdog only while the timing core and
state machine remain valid, the state is not `FAULT`, and no active timing
cause exists. Clearing a timing cause does not make a latched `FAULT` state
feed-eligible.

QEMU proves timer-interrupt routing, deadline arithmetic, single-record
emission and the HAL feed decision. It does not prove CH32V307 register
semantics, interrupt latency, CAN electrical behavior, mechanical stopping
time, bus-off recovery or physical E-stop performance.

## Evidence and boundaries

The shared fake-clock tests cover valid-new activity, rejected activity,
deadline equality, counter wraparound, STOP ACK correlation, exact-deadline
confirmation, late confirmation, STOP timeout, reset gates and invalid input.
The QEMU executable additionally demonstrates timer interrupts, one fault
record and hardware-watchdog expiry after the timing core stops feeding it.

This issue does not implement the Host `SafeCANBus` transport adapter (#55),
command deduplication (#61), HAL CAN drivers, vendor registers, motor control,
bus-off recovery or physical hardware validation.
