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
`J_ENC_L`, `J_ENC_R`). The generated report keeps the legacy `results` partition
and exposes `traction_results` plus `traction_engineering_checks`; all mating
parts and physical continuity/pull evidence remain release blockers.
Each row carries both the declared and required minimum bend radius. Motor
leads H11/H12 require 20 mm, and the validator rejects an under-declared radius
instead of treating a small number as a pass. The same report reads the
candidate motor package and records the 11 A dual-stall demand versus the J2
10 A aggregate ceiling as `BLOCKED_CANDIDATE_EXCEEDS_J2_LIMIT`.

MFG1-8 and MFG10-14 have complete reproducible engineering documents. MFG9 has
a serialized traveller, pilot log, defect taxonomy and analysis method, but cannot
be claimed as physically executed until 20 units complete the route.
