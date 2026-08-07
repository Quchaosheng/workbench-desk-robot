# Mechanical verification matrix

| Task | Evidence | Status / gate |
|---|---|---|
| MECH1 | `cad/desk_robot.scad`, `generated/enclosure.step` | DESIGN COMPLETE; detailed STEP needs CAD-kernel export |
| MECH2 | `generated/bom.csv`, parameterized fastener/mount dimensions | COMPLETE |
| MECH3 | 150 x 72 mm display cutout at Z=225 mm, 8 deg head datum | COMPLETE |
| MECH4 | Chassis, wheelbase, motor bracket datums in SCAD/spec | COMPLETE |
| MECH5 | 1800 mm2 inlet, 2200 mm2 outlet, lower-front to upper-rear | ANALYTICAL PASS; smoke test pending |
| MECH6 | `generated/analysis.json`, 8 mm TPU skin over 24 mm compliant stroke, 35 g target | ANALYTICAL PASS; FEA and drop test pending |
| MECH7 | Manufacturing assembly route `hardware/manufacturing/assembly.md` | COMPLETE |
| MECH8 | SCAD prototype source and BOM | READY FOR PROTOTYPE QUOTE |
| MECH9 | 3 mm dynamic clearance and 5 mm edge clearance rules | CAD INTERFERENCE CHECK pending |
| MECH10 | CG and tip angle in `generated/analysis.json` | ANALYTICAL PASS |
| MECH11 | Physical build and timed record | HOLD: parts required |
| MECH12 | 0.75 m drop video and damage report | HOLD: prototype required |
| MECH13 | Physical fit and 3D scan report | HOLD: production parts required |
| MECH14 | Tool split, shrink, draft and cooling design | HOLD: toolmaker DFM required |
| MECH15 | PC-ABS FR, TPU, aluminium, stainless BOM; supplier declarations | MATERIALS SELECTED; RoHS declarations pending |
| MECH16 | Approved final BOM and drawing ECN | HOLD: MECH11-15 closure required |

## Assembly and tolerance datums

- Datum A: top face of lower chassis; flatness 0.30 mm.
- Datum B: chassis longitudinal centre plane; motor axes symmetric within 0.25 mm.
- Datum C: front display plane; display opening positional tolerance 0.30 mm to B.
- General prototype tolerance: ISO 2768-m; printed parts +/-0.30 mm.
- Injection shell wall 2.5 +/-0.20 mm, draft 1.5 deg minimum, rib thickness 0.55-0.65 times wall.
- Harnesses use 6 mm minimum bend radius for signal wiring and 20 mm for the 48 V trunk.
