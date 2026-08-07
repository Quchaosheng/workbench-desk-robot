# Pilot build and production release

## Twenty-unit pilot log template

Create one row per physical serial; leave results blank until measured.

| Serial | Build date | Touch min | QG first failure | Defect code | Rework cycles | Final result | Evidence URI |
|---|---|---:|---|---|---:|---|---|
| WB1-EVT-001 through WB1-EVT-020 | | | | | | NOT BUILT | |

Pilot report metrics are first-pass yield, rolled throughput yield, defects per unit,
touch time by station, rework time, scrap cost, bottleneck utilization, safety failures,
and top defect Pareto. No placeholder row counts as a built unit.

## Unit cost model

`Unit cost = direct material + touch_hours * burdened_rate + test_time * fixture_rate
+ expected_rework + yield_loss + packaging + inbound/outbound freight + warranty reserve.`

Use actual purchase orders, clocked route data, and pilot yield. The current route
totals 103 touch-minutes; it is a planning baseline, not a quoted labour cost.

## Process ECN content

Every improvement records reason, affected product/process revisions, before/after
method, risk assessment, retraining, fixture/software impact, validation sample size,
effective serial/lot, rollback, and approvals. Safety or interface changes also require
the owning engineer; operators do not release an ECN.

## GO / NO-GO review

Production is **NO-GO** until all conditions below have objective evidence:

- released drawings, PCB data, BOM/AVL, firmware/configuration and packaging revision;
- no open safety, regulatory, isolation, thermal, or structural high-risk item;
- 20/20 pilot units accounted for and all safety tests passed;
- first-pass yield at least 90%, no repeated uncontrolled defect, corrective actions closed;
- calibrated fixtures pass MSA and production software/configuration is access-controlled;
- suppliers and incoming controls approved, critical component traceability demonstrated;
- operator training, work instructions, EHS review, capacity and spares plan complete;
- transport validation passes and field containment/recall traceability is rehearsed.

The manufacturing engineer prepares the evidence pack. Quality, safety, design owners,
and the human product owner make and sign the GO/NO-GO decision.
