# Monitoring collector local evidence (2026-08-19)

Status: **local software measured; target hardware and physical sources NOT_EXECUTED**.

The report was generated on Linux x86_64, Python 3.12.3, Intel Core
i7-14650HX (24 logical CPUs). It is not Jetson Orin or physical robot release
evidence.

```bash
python3 tools/scripts/benchmark_monitoring.py \
  --iterations 10000 \
  --output runs/performance/monitoring.json
```

| Measurement | Local result |
|---|---:|
| CPU per snapshot | 72,963 ns |
| Wall time per snapshot | 72,979 ns |
| RSS before / after | 16,195,584 / 16,207,872 bytes |
| PSS after | 13,584,384 bytes |
| Scheduler context switches during 10,000 snapshots | 7 |
| Threads before / after | 1 / 1 |
| Collector-owned periodic wakeups | 0 |
| Snapshot JSON / Prometheus projection | 8,313 / 840 bytes |

The generated synthetic projections were `healthy` for a complete fresh
snapshot, `unknown` for missing and stale critical sources, and `fault` for an
E-stop channel fault. The raw report stays under the ignored `runs/` path and
can be regenerated with the command above.

These numbers are a development-host regression reference only. Target-class
Jetson CPU/RSS/wakeup/output measurements and calibrated E-stop, BMS, CAN,
Nav2, Motion and perception source evidence remain **NOT_EXECUTED** and must
not be inferred from these fixtures.
