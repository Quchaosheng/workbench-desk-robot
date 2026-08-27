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
  disk use with run duration.
- `status-readers` is the separate Issue #155 comparison profile. It repeatedly
  reads the bounded debugfs status snapshot while using the same latency loop.

Every worker must become active and stop within two seconds. A short write,
worker exception, incomplete activity, stuck worker, partial frame run,
duplicate, unexpected frame, or clock regression produces `FAIL` evidence.

## Repeated campaign

With the module loaded and `wbcan0` up, run:

```bash
sudo make -C kernel/wbcan latency-campaign
```

The default campaign runs three idle repetitions and three controlled-load
repetitions with identical warm-up, sample, CAN ID, commit, kernel, affinity,
clock, and environment fields. Three repetitions are the minimum completeness
budget for this hosted comparison; they are not a latency acceptance threshold.
The bounded limits are 20 repetitions and 100,000 measured samples per run.

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
