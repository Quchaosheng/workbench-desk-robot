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

`MFG1-8` and the planning portions of `MFG10-14` are represented here. `MFG9`
cannot be claimed until 20 physical units have completed the route; the supplied
pilot log is an empty controlled template, not invented production evidence.
