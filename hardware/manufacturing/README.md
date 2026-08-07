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

MFG1-8 and MFG10-14 have complete reproducible engineering documents. MFG9 has
a serialized traveller, pilot log, defect taxonomy and analysis method, but cannot
be claimed as physically executed until 20 units complete the route.
