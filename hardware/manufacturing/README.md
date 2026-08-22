# Manufacturing engineering package

Controlled process baseline for a 20-unit engineering pilot and subsequent
production-readiness review. The route covers receiving, kitting, PCB assembly,
mechanical assembly, firmware-independent electrical checks, functional test,
inspection, packing, and traceability.

```bash
python hardware/manufacturing/tools/validate_route.py
```

Every unit receives a serial number and route traveller. Each quality gate records
operator, fixture ID, calibration status, result, defect code, rework cycle, and
timestamp. A failed safety or isolation check is never bypassed.

Generated controlled records and drawings include:

- `generated/quality-traveller.csv`: fourteen quality gates for one serialized unit.
- `generated/pilot-log.csv`: twenty preallocated EVT serials, all initially `NOT_BUILT`.
- `generated/unit-cost-inputs.csv`: auditable cost inputs and evidence sources.
- `generated/line-layout.svg`: one-way U-cell with fenced MRB/quarantine.
- `generated/fixture-drawings.svg`: datum nest and guarded electrical fixture dimensions.
- `generated/packaging-drawing.svg`: transit-pack section and protection requirements.
- `harness-spec.csv`: controlled battery, rail, data, CAN and safety harness envelope.
- `generated/harness_report.json`: calculated voltage drop, current density, bend-radius and release gates.

The harness specification retains the H01-H08 controller baseline and adds the
H09-H14 traction childboard endpoints (`J_SAFE`, `J_CAN`, `J_ML`, `J_MR`,
`J_ENC_L`, `J_ENC_R`). H02 is the shared controller-J2-to-childboard-J_PWR
power harness and is included in the explicit integration view. Every row now
declares source/destination endpoints, a pin map, active-level semantics, shield
semantics and drain termination semantics. H11/H12 terminate at the external
M1/M2 motor terminals; H13/H14 terminate at the external encoder pins. The
generated report keeps the legacy `results` partition and exposes
`traction_results`, `integration_results` and `traction_engineering_checks`; all
mating parts and physical continuity/pull evidence remain release blockers.
Each row carries both the declared and required minimum bend radius. Motor
leads H11/H12 require 20 mm, and the validator rejects an under-declared radius
instead of treating a small number as a pass. The same report reads the
candidate motor package and records the 11 A dual-stall demand versus the J2
10 A aggregate ceiling as `BLOCKED_CANDIDATE_EXCEEDS_J2_LIMIT`.
CAN harnesses use three signal conductors plus a separate shield drain; encoder
harnesses use four signal conductors plus a separate shield drain. Neither drain
is assigned to the reserved NC connector pin; its chassis termination remains a
deliberate TBD until the EMC/supplier review closes.

`J_SAFE` is an ECO-only controller endpoint for two independent hardwired safety
channels. It is not the current four-pin J11, whose H08 harness remains a
single `MOTOR_ENABLE_SAFE` plus diagnostic endpoint and is explicitly unsuitable
for the childboard A/B safety input.

MFG1-8 and MFG10-14 have complete reproducible engineering documents. MFG9 has
a serialized traveller, pilot log, defect taxonomy and analysis method, but cannot
be claimed as physically executed until 20 units complete the route.
