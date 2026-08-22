# ADR-0005: Unified Hardware Device Runtime and DDS Boundary

Status: **proposed** (Issue #230; requires Linux, Integration, Motion and
Perception owner review)

Date: 2026-08-22

## Context

The repository has several planned hardware inputs and outputs: SocketCAN,
cameras and touch devices, arm drivers, and a hardware safety bridge. Their
README files currently describe separate adapters, while the runtime and
backend only have a simulation/event-store path. There is no shared contract
for worker lifecycle, queue bounds, cancellation, provenance, or external
exposure. Fast DDS is not a current project dependency.

The kernel `wbcan` module is a virtual SocketCAN fault harness. It must not be
turned into a hardware framework, and a DDS path must not become a substitute
for the independent E-stop, watchdog, or safe-enable circuit.

## Decision

Introduce a transport-neutral `DeviceRuntime` boundary in a later, separately
reviewed implementation slice:

```text
physical device / Linux driver
  -> DeviceAdapter (CAN, camera, touch, arm, safety monitor)
  -> bounded DeviceRuntime (lifecycle, workers, queues)
  -> typed ROS 2 topic/service/action boundary
  -> selected RMW (Fast DDS in the target deployment)
  -> validation + provenance envelope
  -> World Model / ActionResult / evidence sink
  -> read-only external projection
```

### Adapter and runtime ownership

- A `DeviceAdapter` owns blocking device I/O and translates it to a typed
  envelope. It does not write WorldState, call HTTP, or expose a raw handle.
- `DeviceRuntime` owns `configure -> activate -> deactivate -> cleanup`,
  cancellation, worker joins, queue limits, backpressure and health counters.
- A ROS 2 wrapper should use `rclcpp_lifecycle::LifecycleNode` (or the
  equivalent lifecycle API) so lifecycle transitions create and destroy the
  adapter workers and DDS entities as one idempotent operation. A failed
  activation must not leave a half-active publisher or device handle.
- Each device's mutable state has one writer. Callbacks hand work to a bounded
  queue instead of mutating state concurrently.
- Bridge, device and touch implementations are plugins of the same port; their
  hardware-specific code stays outside the common runtime.

### Threads and queues

- Use one blocking I/O worker per device or a documented bounded worker pool;
  never create an unbounded thread per message.
- ROS 2 callback groups and a bounded `MultiThreadedExecutor` may dispatch
  callbacks, but a DDS callback must not block on hardware I/O.
- Every queue has a fixed capacity and an explicit policy: reject commands,
  retry boundedly, or drop old telemetry with a counter. Queue-full, deadline,
  link-loss, duplicate and late-frame outcomes are observable.
- Shutdown cancels producers first, drains or rejects according to the port
  contract, joins workers with a deadline, then destroys the DDS participant,
  timers and file descriptors. A timeout is an error, not a silent daemon.

### DDS and ROS 2 boundary

The core depends on typed ROS 2 interfaces and an injected transport port, not
on Fast DDS symbols. Deployment may select Fast DDS with
`RMW_IMPLEMENTATION=rmw_fastrtps_cpp`; another supported RMW must remain a
possible test backend. The bridge Task Packet must record domain ID, topic or
service names, QoS, security/permissions and discovery behavior.

Default QoS policy is explicit and per data class:

| Data class | Default policy | Failure meaning |
| --- | --- | --- |
| sensor/touch telemetry | bounded best-effort, keep-last | dropped sample is counted and freshness can expire |
| command/ACK | reliable, bounded depth, deadline and correlation | no ACK is timeout/fault, never success |
| health/provenance | reliable, bounded and sequence-checked | missing or regressed record is not ready |
| E-stop/watchdog | hardware/out-of-band authority | DDS is monitor-only, never the sole stop path |

### Validation and external exposure

The runtime validates frame kind, source/interface identity, sequence, clocks,
payload and freshness before publishing a consumer-visible record. It preserves
the existing distinction between dispatch state, device state, verification
state and evidence. Direct framework exposure is allowed only for validated,
read-only telemetry and health. Commands continue through trusted Motion,
MCU and Safety owners; the dashboard and HTTP API never gain a device writer.

Hardware and simulation adapters must emit the same consumer contract. A fake
transport and ROS loopback can prove ordering, lifecycle and metadata, but they
cannot prove physical CAN, actuator, touch-safety or hard-real-time behavior.

## Rollout

1. Define the transport-neutral port and envelope without changing frozen
   public schemas.
2. Add a fake adapter and one SocketCAN adapter with lifecycle, saturation,
   cancellation, duplicate/late-frame and callback-failure tests.
3. Add the ROS 2 bridge and Fast DDS deployment configuration with recorded QoS
   and security settings.
4. Add camera/touch and arm plugins independently; do not combine their
   bring-up or safety evidence with the CAN PR.
5. Feed only validated records to the existing event/evidence path and expose
   them through the existing read-only projection.

## Alternatives rejected

- **Device directly to HTTP.** Bypasses validation, provenance and the
  read-only boundary.
- **Fast DDS types in every adapter.** Couples hardware code to one middleware
  and makes deterministic fake testing harder.
- **One global unbounded thread/queue.** Hides backpressure and lets a noisy
  sensor starve command or safety diagnostics.
- **DDS as the safety channel.** Discovery, scheduling and network failures do
  not replace the hardware E-stop/watchdog path.

## Open decisions

The implementation PR must settle the concrete ROS 2 message package, DDS
domain/security profile, executor sizing, queue capacities and physical device
permissions with the named owners. Until then this ADR is a design proposal,
not a claim that Fast DDS or physical hardware is implemented.
