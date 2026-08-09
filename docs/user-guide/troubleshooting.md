# Troubleshooting

Troubleshooting is evidence-first and remote-first. Never bypass protection or
repeat an energization that produces smoke, odor, heat, battery alarm, uncontrolled
motion, or a safety-chain failure.

| Symptom | Safe first checks | Escalate when |
|---|---|---|
| no power | service disconnect, approved charger, visible damage, BMS state | battery damage, fuse operation, repeated trip |
| stuck in precharge | bus/load disconnected state, event log, pack/config revision | timeout repeats or contactor feedback disagrees |
| derated | temperature, SOC, current demand, cooling obstruction | threshold persists after safe cooldown |
| arm not ready | E-stop, guard/interlock, calibration, controller status | mismatch repeats or brake/position is abnormal |
| communication loss | approved cables, switch/link state, timestamps, service health | intermittent fleet pattern or safety data loss |
| task failure | payload/tool identity, workspace, evidence bundle, last known state | collision, dropped object, repeated recovery |

Capture the case template before changing configuration. Export logs with checksum
and time range. Record every attempted action and its result. Use only approved,
reversible recovery steps. If an update or rollback is authorized, verify artifact
signature/hash, stable power, backup, abort criteria, and post-change acceptance.

For S0/S1 conditions, stop use and apply fleet containment before root cause is
complete. Returned units and storage devices follow chain-of-custody and privacy
rules. A no-fault-found outcome still requires the evidence and reproduction record.
