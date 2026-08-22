# Mechanical verification matrix

| Task | Evidence | Status / gate |
|---|---|---|
| MECH1 | Revision B SCAD, assembly STEP, enclosure and six part STEP files | ENGINEERING COMPLETE; CAD REGENERATION REQUIRED |
| MECH2 | `generated/bom.csv`, parameterized fastener/mount dimensions | COMPLETE |
| MECH3 | Separate 190 x 72 x 92 mm head, recessed 150 x 72 display, 8 deg datum | COMPLETE |
| MECH4 | Assembly STEP, low chassis, wheel pods, service panel and datums | ENGINEERING COMPLETE; PHYSICAL FIT REQUIRED |
| MECH5 | `drawings/thermal-flow.svg`, 1800/2200 mm2 flow path | ENGINEERING COMPLETE; smoke test external |
| MECH6 | analysis and drop-screening JSON, 24 mm stroke, 35 g target | SCREEN COMPLETE; nonlinear FEA/drop external |
| MECH7 | exploded STEP, assembly sequence and manufacturing route | COMPLETE |
| MECH8 | six part STEP files, SCAD source and BOM | READY FOR PROTOTYPE QUOTE |
| MECH9 | assembly STEP and minimum-clearance rules | DIGITAL CHECK COMPLETE; physical fit external |
| MECH10 | CG and tip angle in `generated/analysis.json` | ANALYTICAL PASS |
| MECH11 | exploded assembly and timed manufacturing route | EXECUTION READY; parts required |
| MECH12 | 0.75 m method, limits and report fields | EXECUTION READY; prototype required |
| MECH13 | assembly model, datums and fit acceptance | EXECUTION READY; production parts required |
| MECH14 | wall/rib/draft baseline and supplier gate | RFQ READY; toolmaker DFM required |
| MECH15 | PC-ABS FR, TPU, aluminium, stainless BOM; supplier declarations | MATERIALS SELECTED; RoHS declarations pending |
| MECH16 | revision-controlled BOM/ECN gate | TEMPLATE COMPLETE; approvals required |

## Assembly and tolerance datums

- Datum A: top face of lower chassis; flatness 0.30 mm.
- Datum B: chassis longitudinal centre plane; motor axes symmetric within 0.25 mm.
- Datum C: front display plane; display opening positional tolerance 0.30 mm to B.
- General prototype tolerance: ISO 2768-m; printed parts +/-0.30 mm.
- Injection shell wall 2.5 +/-0.20 mm, draft 1.5 deg minimum, rib thickness 0.55-0.65 times wall.
- Harnesses use 6 mm minimum bend radius for signal wiring and 20 mm for the 48 V trunk.
- Revision B shoulder draft target: 6 deg; head-to-neck moving clearance: 3 mm.
- Wheel pod guard clearance: 3 mm; display bezel target: 3 mm; rear service-panel
  clearance: 20 mm.
