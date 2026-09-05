# Host CAN transport adapter V1

Status: **bounded host-adapter and SocketCAN ingress contract** for Issues #55
and #229.

`SafeCANBus` is the CAN `DeviceAdapter` for the unified `DeviceRuntime`
defined by ADR-0005. It owns the injected blocking transport port and the
CAN Wire V1 protocol state, but it does not own a lifecycle, worker, queue or
subscriber registry. `SocketCANTransport` is the standard-library
`AF_CAN`/`CAN_RAW` implementation of that port: it owns one raw file
descriptor, applies kernel filters, and translates one bounded
`struct can_frame` at a time. Construction never opens SocketCAN or any
hardware device, and a successful queue or write never means that an MCU
accepted a command.

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

The runtime owns four independent bounded planes:

| Plane | Owner and policy | Observable boundary |
| --- | --- | --- |
| command/ACK | fixed command queue; reject ordinary commands at capacity; STOP is priority and preempts | typed backpressure, correlation and timeout diagnostics |
| telemetry | fixed ingress queue; duplicate/stale frames are rejected before dispatch | telemetry depth and drop counter |
| health/provenance | fixed diagnostic queue with oldest-record eviction | error and health-drop counters |
| external projection | immutable read-only records with oldest-record eviction | external depth and drop counter |

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
evidence references. SocketCAN records additionally preserve the raw CAN ID,
DLC, kernel `SO_TIMESTAMPNS` timestamp, `SO_RXQ_OVFL` counter when supplied,
and host observation clocks. The adapter-ingress sequence is never reset by
link recovery; the separate MCU telemetry sequence follows the Wire V1
half-range ordering rule. A non-finite or regressed clock observation is an
observable fail-closed ingress error and is not silently normalized. A bridge
may map the envelope to the later typed ROS 2/event contract without exposing
a raw device handle.

## SocketCAN ingress contract

`SocketCANTransport` performs the following boundary checks before
`decode_can_frame()` runs:

1. Open exactly one `AF_CAN`, `SOCK_RAW`, `CAN_RAW` socket and bind it to the
   configured interface. No adapter-local worker, queue, retry loop or second
   lifecycle state machine is created.
2. Install typed `CAN_RAW_FILTER` entries. A filter includes the selected
   standard/extended/RTR/error flag bits in its mask, so a frame-kind variant
   cannot match accidentally. The optional CAN error mask remains separate
   from protocol-frame filters.
3. Enable a bounded receive buffer, `SO_RXQ_OVFL`, and (by default)
   `SO_TIMESTAMPNS`. `poll()` and non-blocking `recvmsg()` are used for one
   record per call. `MSG_TRUNC`, `MSG_CTRUNC`, malformed ancillary data, short
   records, CAN-FD-sized records, invalid DLC, and contradictory raw-ID flags
   become observable frame rejections.
4. Preserve standard, extended, RTR and error flags in an immutable
   `CanFrame`. Error frames are never passed to Wire V1 decoding; a bus-off
   error moves the adapter to `BUS_OFF` and clears pending work.
5. Only standard, non-RTR, non-error, DLC-8 frames with a known Wire V1 ID,
   version, reserved bytes and valid cross-fields enter the protocol/runtime
   boundary. ACK, STOP_ACK and telemetry are the only inbound kinds.

`CanExternalRecord` is the only projection intended for an external observer.
It contains source/interface identity, ingress sequence, frame metadata,
timestamps and source, event/protocol fields, health, evidence reference and
whether the frame was valid and exposed. It contains immutable `bytes` only;
it never contains a socket, file descriptor, callback, debugfs path or write
handle. Accepted ACK/STOP_ACK/telemetry records may be exposed. Duplicate,
late, uncorrelated, malformed, error and post-shutdown records remain
observable rejections (through `CanReceiveResult` and bounded diagnostics while
the runtime is active), but they are deliberately excluded from the external
projection queue and cannot claim completion.

## Concurrency and backpressure

The runtime's data planes, subscriber registry, error counter and the
adapter's correlation windows are protected by one shared lock. Subscriber
dispatch uses an immutable snapshot, so a callback may subscribe or
unsubscribe without changing the current iteration. Callback exceptions are
isolated and recorded.

Command, telemetry, health, external projection, subscriber and correlation
capacities are fixed by `CanTransportConfig`. Queue saturation returns a typed
backpressure result and increments a bounded drop counter. `shutdown()` stops
the runtime worker, clears pending work and external records, joins the worker
by the caller's deadline, and only then closes the injected port. A frame that
returns from a receive racing with shutdown is not dispatched or published.
There is no adapter-local fallback worker or unbounded callback path.

## Evidence and recovery boundary

`kernel/wbcan/test_socketcan_ingress.py` is a deterministic virtual probe. It
uses a real SocketCAN fd and a second peer socket to send a Wire V1 command,
return an ACK, return telemetry, replay a duplicate ACK and send a wrong-DLC
frame. It writes `socketcan-ingress-report-v1` with `PASS`, `FAIL` or
`NOT_EXECUTED`, exact external records and cleanup checks. `--require-pass` is
appropriate only in a privileged CI job whose virtual prerequisites are
present.

Recovery is deliberately two-stage: the CAN administrator or supervisor
restores the interface, then the configured transport recovery probe confirms
that operation. `SafeCANBus.recover()` clears pre-fault commands and
correlation state; it never replays them. A physical adapter, firmware/MCU,
actuator, electrical bus, PREEMPT_RT scheduler or hard-real-time deadline is
outside this virtual probe and must remain `NOT_EXECUTED` until the physical
HIL procedure records the required raw evidence and owner review.

## Evidence limits

The fake transport and fake clock tests prove adapter state transitions,
validation, bounded retry and lifecycle behavior only. The SocketCAN probe
proves a virtual Linux SocketCAN ingress and projection path when it returns
`PASS`. Neither evidence class proves physical CAN arbitration, MCU
acceptance, actuator motion, PREEMPT_RT behavior, electrical integrity or a
hard-real-time deadline.
