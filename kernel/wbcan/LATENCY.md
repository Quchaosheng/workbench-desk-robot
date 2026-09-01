# wbcan virtual latency evidence

The latency probe measures userspace-observed native SocketCAN send-to-receive
time with `monotonic_ns`. It exercises the virtual `wbcan` netdevice only. Its
reports are not physical CAN, controller IRQ, transceiver, MCU, actuator,
PREEMPT_RT, or hard-real-time evidence.

## Profiles

- `idle` runs only the bounded measurement loop.
- `controlled-load` runs a fixed number of CPU and I/O workers while measuring.
  Each CPU worker repeatedly hashes a fixed 64 KiB in-memory buffer. Each I/O
  worker repeatedly overwrites and `fsync`s one 4 KiB temporary file at offset
  zero, then uses `fstat` to verify its bounded size. The report records every
  worker's observed iterations, logical bytes written, and observed maximum file
  size. Temporary files are removed after each run, so the profile does not grow
  disk use with run duration. Each worker completes its first-use allocation,
  file setup, and setup verification before publishing `ready`. The parent waits
  for every worker, starts the monotonic and process-CPU clocks, and then opens
  one common start gate. Consequently, setup is outside the controlled-load
  measurement window and the idle and controlled-load windows are comparable.
- `status-readers` is the separate Issue #155 comparison profile. It repeatedly
  reads the bounded debugfs status snapshot while using the same latency loop.

Every worker must become ready within two seconds and stop within the bounded
shutdown deadline. Shutdown first requests cooperative stop and then uses
bounded `terminate`/`kill` fallbacks. The parent verifies that every worker is
no longer alive and has an exit status before closing its process handle. A
readiness timeout, cooperative-stop timeout, forced termination, non-zero exit,
unverified shutdown, short write, worker exception, incomplete activity, partial
frame run, duplicate, unexpected frame, or clock regression produces `FAIL`
evidence. A worker that does not produce measured activity is also rejected.

## Repeated campaign

The authoritative execution path is the privileged GitHub Actions
`kernel-module` job. It builds and loads `wbcan`, runs the complete driver gate,
then records and uploads the repeated idle/controlled-load reports together
with the strict campaign JSON. On a Linux host with matching headers, root
access, debugfs, and `wbcan0` available, the equivalent local command is:

```bash
sudo make -C kernel/wbcan latency-campaign
```

The default campaign runs three idle repetitions and three controlled-load
repetitions with identical warm-up, sample, CAN ID, commit, kernel, affinity,
clock, and environment fields. Three repetitions are the minimum completeness
budget for this hosted comparison; they are not a latency acceptance threshold.
The bounded limits are 20 repetitions and 100,000 measured samples per run.

If a local environment cannot build/load the module or access debugfs (for
example, WSL without headers matching its running kernel), leave the runtime
campaign `NOT_EXECUTED` locally and use the hosted `kernel-module` result as the
virtual-wbcan runtime evidence. A hosted PASS does not extend the claim beyond
that runner: physical CAN, MCU, actuator, PREEMPT_RT, and hard-real-time
validation remain `NOT_EXECUTED`.

The two profile reports preserve every run's P50/P95/P99/max, population
standard-deviation jitter, optional deadline misses, elapsed time, process CPU
time, throughput, delivery counters, and load activity. The campaign report
binds both source reports by SHA-256 and gives min/nearest-rank-median/max
observational envelopes plus signed median deltas. It deliberately has no
latency PASS/FAIL threshold and cannot establish an SLA from hosted-runner data.

Default output files are:

- `/tmp/wbcan-latency-idle.json`
- `/tmp/wbcan-latency-controlled-load.json`
- `/tmp/wbcan-latency-campaign.json`

Validate saved evidence independently:

```bash
python3 kernel/wbcan/test_latency.py --validate-report /tmp/wbcan-latency-idle.json
python3 kernel/wbcan/test_latency.py --validate-report /tmp/wbcan-latency-controlled-load.json
python3 kernel/wbcan/validate_latency_campaign.py \
  --validate-report /tmp/wbcan-latency-campaign.json
```

Keep reports from different kernels, commits, CPU affinities, CAN IDs, sample
budgets, or deadlines as separate campaigns. Do not combine their percentiles
or present a virtual comparison as physical or real-time qualification.
