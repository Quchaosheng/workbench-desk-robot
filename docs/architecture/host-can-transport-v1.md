# Host CAN transport adapter V1

Status: **bounded host-adapter contract** for Issue #55.

`SafeCANBus` owns a small injected transport port. It does not open SocketCAN
or any hardware device in its constructor, and it does not claim that a
successful queue or write means that an MCU accepted a command.

## Safety and ownership boundary

- `firmware/mcu/core/frame_codec.[ch]` remains the authority for the binary
  Wire V1 layout. The Python adapter duplicates only the bounded ingress
  validation needed before a frame crosses the host boundary; it does not
  change the wire numbers or logical protocol.
- The adapter accepts only standard 11-bit, non-remote, non-error, DLC-8
  frames with known Wire V1 identifiers and complete cross-field semantics.
- Ordinary commands have one bounded in-flight request. A successful local
  transport dispatch starts an acknowledgement deadline; it is not command
  completion.
- Retry attempts retain command correlation and increment the on-wire retry
  count. The retry budget is finite. Exhaustion clears ordinary traffic and
  emits a correlated STOP request.
- STOP preempts queued and pending ordinary traffic. STOP acknowledgement
  timeout, rejected STOP, bus-off, and link loss leave the adapter unable to
  send ordinary commands until an explicit successful recovery.
- Recovery clears queued and pending pre-fault frames. It never replays stale
  traffic. The caller must establish any higher-level session/startup gate.

## Concurrency and backpressure

The outbound queue, subscriber registry, error counter, diagnostics and
correlation windows are protected by one lock. Subscriber dispatch uses an
immutable snapshot, so a callback may subscribe or unsubscribe without
changing the current iteration. Callback exceptions are isolated and recorded.

Queue capacity, subscriber count, diagnostic count and correlation count are
fixed by `CanTransportConfig`. Queue saturation returns a typed backpressure
result. `shutdown()` stops the worker, clears pending work, and closes the
injected port within a caller-supplied bound.

## Evidence limits

The fake transport and fake clock tests prove adapter state transitions,
validation, bounded retry and lifecycle behavior only. They are not evidence
of SocketCAN operation, physical CAN arbitration, MCU acceptance, actuator
motion, or a hard-real-time deadline.
