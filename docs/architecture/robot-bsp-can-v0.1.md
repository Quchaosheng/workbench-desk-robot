# Robot BSP CAN Contract V0.1

Status: logical multi-domain contract frozen for prototype integration. CAN
controller, bitrate, transceiver, wiring and physical timing remain pending
electrical approval.

## Node allocation

| Domain | Node ID | Reset domain | Heartbeat |
|---|---:|---|---|
| Linux gateway | `0x01` | Linux board | host health, 100 ms |
| `MCU-BASE` | `0x10` | base motion | 50 ms |
| `ARM-L-CTRL` | `0x11` | left arm | 50 ms |
| `ARM-R-CTRL` | `0x12` | right arm | 50 ms |
| `TOOL-L-CTRL` | `0x13` | left tool | 100 ms |
| `TOOL-R-CTRL` | `0x14` | right tool | 100 ms |
| `MCU-SAFETY` | `0x1F` | independent safety | 20 ms |

Node IDs identify control domains, not necessarily individual chips. A vendor
arm controller may contain several internal processors but must expose one
domain identity at this boundary.

## Message priority

The existing MCU Wire V1 frame kinds remain authoritative. The prototype
arbitration layout reserves the highest-priority ranges for stop and fault
traffic; exact bit allocation is an electrical/controller implementation gate.

| Traffic | Priority | Direction | Rule |
|---|---|---|---|
| STOP / stop acknowledgement | highest | Linux or safety to domain / domain to Linux | accepted from every state; idempotent; no ordinary traffic can consume its sequence space |
| safety fault / inhibit | very high | safety/domain to Linux | latched until the documented reset cause is cleared |
| command / acknowledgement | normal | Linux to domain / domain to Linux | bounded deadline, correlation ID, duplicate and late result handling |
| heartbeat | high | domain to Linux | timeout enters the domain-specific degraded state |
| telemetry | low | domain to Linux | bounded best-effort queue; drops counted, never treated as command completion |

## Failure behavior

- Missing `MCU-SAFETY` heartbeat: hardware safety chain remains inhibited; Linux
  must not attempt an automatic enable.
- Missing `MCU-BASE`, arm or tool heartbeat: that domain is faulted and its
  commands are rejected; other domains do not infer success from its absence.
- Linux restart: all motion domains remain disabled until fresh discovery,
  heartbeats and an owner-authorized reset sequence complete.
- MCU restart: boot ID changes; old acknowledgements and telemetry cannot be
  correlated to the new boot.
- CAN bus-off: expose SocketCAN restart state, retain fault counters and keep
  the affected domain inhibited until recovery is confirmed.
- Duplicate command: return the original correlated result when the payload
  matches; conflicting reuse of an ID is a fault/rejection.
- Late acknowledgement: record as late/unmatched and never mutate a newer
  action or claim completion.

## Required implementation evidence

Before physical bring-up, the BSP implementation must add a concrete
arbitration-ID table, bitrate/FD data phase, termination, transceiver part,
device-tree nodes, and per-domain recovery tests. `wbcan` can validate the
software semantics, but cannot provide bus-load, EMC, wire-latency or physical
recovery evidence.
