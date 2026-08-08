# 48-hour reliability protocol

The 48-hour run starts only after the QA and safety owners approve the unit and
the first-batch acceptance gate is closed. Use the production candidate
configuration, a synchronized monotonic clock, and an append-only event log.

Record heartbeat, CAN error counters, rail voltage/current, temperatures,
E-stop state, watchdog resets, operator interventions, and every stop reason at
one-minute intervals or on event. Stop immediately for safety violation,
over-temperature, uncontrolled motion, isolation failure, repeated watchdog
reset, or data loss. A stopped run is a failure sample, not a successful partial
run.

Acceptance requires 48 continuous hours, no unclassified safety or power fault,
all interventions classified, and a signed report containing raw logs, summary
statistics, and the final configuration hash. The repository currently contains
the protocol only; no 48-hour result is claimed.
