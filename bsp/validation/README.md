# BSP Validation Evidence

Store raw bring-up captures outside source control when they contain sensitive
device details, and commit only immutable manifests and hashes.

Every record must identify board revision, kernel/JetPack version, firmware
versions, node IDs, instrument/calibration references, UTC timestamp, command
and result (`PASS`, `FAIL` or `NOT_EXECUTED`).

Minimum evidence set:

- Linux cold/warm boot and recovery transcript
- device-tree and interface enumeration
- CAN discovery and six-domain heartbeat capture
- STOP and independent E-stop timing capture
- per-domain reset and Linux restart behavior
- bus-off/restart counters and bounded queue behavior
- CPU, memory, temperature, power and CAN bus-load samples

`PASS` here means only that the named test ran and met its stated criterion. It
does not authorize production release; hardware release gates remain governed
by `hardware/release/`.
