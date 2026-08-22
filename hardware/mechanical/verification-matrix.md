# Mechanical verification matrix

| Task | Evidence | Status / gate |
|---|---|---|
| MECH1 | SCAD, assembly STEP, enclosure, eight part STEP files and eight TBD envelope STEP files | ENGINEERING COMPLETE; ENVELOPE SELECTION OPEN |
| MECH2 | `generated/bom.csv`, parameterized fastener/mount dimensions | COMPLETE |
| MECH3 | 150 x 72 mm display cutout at Z=225 mm, 8 deg head datum | COMPLETE |
| MECH4 | Assembly STEP, chassis/motor bracket STEP, two traction-motor and four wheel envelopes, datums | ENVELOPE COMPLETE; MOTOR/WHEEL SELECTION AND LOAD VALIDATION OPEN |
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
| MECH17 | independent driver-childboard envelope, removal and connector corridors | DIGITAL ENVELOPE PASS; FINAL OUTLINE/THERMAL/PHYSICAL FIT OPEN |
| MECH18 | four wheel envelopes at controlled wheelbase, track and ground contact | DIGITAL ENVELOPE PASS; HUB/TYRE/BEARING/LOAD/SWEEP VALIDATION OPEN |
| MECH19 | battery envelope, thermal clearances, support and impact-restraint reservation | DIGITAL CLEARANCE PASS; PACK/RESTRAINT/IMPACT VALIDATION OPEN |

## Assembly and tolerance datums

- Datum A: top face of lower chassis; flatness 0.30 mm.
- Datum B: chassis longitudinal centre plane; motor axes symmetric within 0.25 mm.
- Datum C: front display plane; display opening positional tolerance 0.30 mm to B.
- General prototype tolerance: ISO 2768-m; printed parts +/-0.30 mm.
- Injection shell wall 2.5 +/-0.20 mm, draft 1.5 deg minimum, rib thickness 0.55-0.65 times wall.
- Harnesses use 6 mm minimum bend radius for signal wiring and 20 mm for the 48 V trunk.
- Datum D: traction motor envelope centres at X = -86/+86 mm, Y = 0 mm; these are reserved centres pending approved shaft and mount geometry.
- Datum E: driver-childboard envelope centre [0, 54, 150] mm; reserve +Z removal and +Y rear connector access until the physical service trial closes.
- Datum F: battery reservation centre [0, 0, 52] mm; keep a 20 mm analytical heat-source gap and reserve a removable BMS/impact restraint until pack selection.
