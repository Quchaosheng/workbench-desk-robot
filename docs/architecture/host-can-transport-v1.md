# Host CAN transport adapter V1

Status: **bounded host-adapter contract** for Issue #55.

`SafeCANBus` is the CAN `DeviceAdapter` for the unified `DeviceRuntime`
defined by ADR-0005. It owns the injected blocking transport port and the
CAN Wire V1 protocol state, but it does not own a lifecycle, worker, queue or
subscriber registry. Construction never opens SocketCAN or any hardware
device, and a successful queue or write never means that an MCU accepted a
command.

## Unified runtime ownership

`DeviceRuntime` is the only owner of:

```text
configure -> activate -> one I/O worker -> deactivate -> cleanup
                     |                    |
             cancellation + join     bounded data planes
```

The legacy `SafeCANBus.start()`, `service_once()` and `shutdown()` methods are
compatibility delegates to that runtime. `CanLinkState` reports CAN link and
protocol health only; it is not a second lifecycle state machine. The adapter
implements `configure`, `activate`, `poll`, `deactivate` and `cleanup`, and
uses the runtime's one lock when it updates protocol correlation state.

The runtime owns three independent bounded planes:

| Plane | Owner and policy | Observable boundary |
| --- | --- | --- |
| command/ACK | fixed command queue; reject ordinary commands at capacity; STOP is priority and preempts | typed backpressure, correlation and timeout diagnostics |
| telemetry | fixed ingress queue; duplicate/stale frames are rejected before dispatch | telemetry depth and drop counter |
| health/provenance | fixed diagnostic queue with oldest-record eviction | error and health-drop counters |

Subscriber registration and callback snapshot dispatch also belong to the
runtime. Callback exceptions are isolated and become health records. A
shutdown cancels producers, rejects new commands, clears queued work, joins
the single worker by deadline, and only then lets the adapter close the port.
A join timeout leaves cleanup pending and returns `False`; a later call may
retry. A terminal cleanup result is retained, so a lifecycle label cannot be
mistaken for successful cleanup.

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
- Telemetry uses the protocol half-range ordering rule. Duplicate and stale
  snapshots are ignored, while valid fault telemetry disables ordinary traffic
  until explicit transport recovery.

Every valid inbound result carries an immutable `CanTransportEnvelope` with
`source`, `interface`, an adapter-ingress sequence, monotonic and wall-clock
observation times, current link health, the validated wire frame and immutable
evidence references. The adapter-ingress sequence is never reset by link
recovery; the separate MCU telemetry sequence follows the Wire V1 half-range
ordering rule. A non-finite or regressed wall-clock observation is an
observable `clock_rollback` ingress error and blocks normal commands; it is
not silently normalized. A bridge may map this envelope to the later typed
ROS 2/event contract without exposing a raw device handle.

## Concurrency and backpressure

The runtime's data planes, subscriber registry, error counter and the
adapter's correlation windows are protected by one shared lock. Subscriber
dispatch uses an immutable snapshot, so a callback may subscribe or
unsubscribe without changing the current iteration. Callback exceptions are
isolated and recorded.

Command, telemetry, health, subscriber and correlation capacities are fixed by
`CanTransportConfig`. Queue saturation returns a typed backpressure result.
`shutdown()` stops the runtime worker, clears pending work, and closes the
injected port within a caller-supplied bound. There is no adapter-local
fallback worker or unbounded callback path.

## Evidence limits

The fake transport and fake clock tests prove adapter state transitions,
validation, bounded retry and lifecycle behavior only. They are not evidence
of SocketCAN operation, physical CAN arbitration, MCU acceptance, actuator
motion, or a hard-real-time deadline.
