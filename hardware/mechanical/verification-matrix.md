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
| MECH8 | eight part STEP files, SCAD source and BOM | READY FOR PROTOTYPE QUOTE |
| MECH9 | assembly STEP and minimum-clearance rules | DIGITAL CHECK COMPLETE; physical fit external |
| MECH10 | CG and tip angle in `generated/analysis.json` | ANALYTICAL PASS |
| MECH11 | exploded assembly and timed manufacturing route | EXECUTION READY; parts required |
| MECH12 | 0.75 m method, limits and report fields | EXECUTION READY; prototype required |
| MECH13 | assembly model, datums and fit acceptance | EXECUTION READY; production parts required |
| MECH14 | wall/rib/draft baseline and supplier gate | RFQ READY; toolmaker DFM required |
| MECH15 | PC-ABS FR, TPU, aluminium, stainless BOM; supplier declarations | MATERIALS SELECTED; RoHS declarations pending |
| MECH16 | revision-controlled BOM/ECN gate | TEMPLATE COMPLETE; approvals required |
| MECH17 | independent driver-childboard envelope, fixed support datums, removal and connector corridors | DIGITAL ENVELOPE/FIXED-DATUM PASS; FINAL OUTLINE/THERMAL/PHYSICAL FIT OPEN |
| MECH18 | four wheel envelopes at controlled X-axis track, Y-axis wheelbase, lateral X axles, local chassis wheel-well cuts, shell/well clearance and ground contact | DIGITAL ENVELOPE/TOLERANCE ALLOCATION PASS; HUB/TYRE/BEARING/LOAD/SWEEP VALIDATION OPEN |
| MECH19 | battery envelope, thermal clearances, support and impact-restraint reservation | DIGITAL CLEARANCE PASS; PACK/RESTRAINT/IMPACT VALIDATION OPEN |
| MECH20 | 1200 x 800 dual-arm RHS chassis, fixed lower frame, four guided telescoping columns, moving upper frame, local crossmembers and deck | DIGITAL STRUCTURE COMPLETE; FEA/BUCKLING/WELD/PROOF-LOAD OPEN |
| MECH21 | two undrilled 300 x 300 x 25 S355 arm plates at controlled +/-300 mm bases for purchased seven-axis arms | DIGITAL RESERVED-ZONE PASS; PURCHASED-REVISION PATTERN/LOAD/TORQUE OPEN |
| MECH22 | four 300 kg transport casters and four deployable 300 kg leveling outriggers with independent ratings and support polygon | ANALYTICAL LOAD ALLOCATION PASS; MPN/LOCK/SETUP/STABILITY TEST OPEN |
| MECH23 | separate controller bays, battery/ballast tray, rear/riser cable trays, bond studs and service directions | DIGITAL CLEARANCE PASS; PACK/CABINET/HARNESS/BOND VALIDATION OPEN |
| MECH24 | full-system assembly STEP, structural/lift part STEP files, seven supplier envelopes, BOM and assembly sequence | REPRODUCIBLE ENGINEERING PACKAGE; SUPPLIER AND PHYSICAL GATES OPEN |
| MECH25 | conservative 368 kg maximum-lift case, 1200 x 960 support polygon and 38.6/31.0 degree static tip screen | ANALYTICAL PASS; MEASURED MASS/CG/MAX-HEIGHT PULL TEST OPEN |
| MECH26 | 750-1100 mm four-column synchronized lift, redundant limits, per-column feedback, 2 mm skew limit, positive locks and arm/lift interlock contract | DIGITAL CONTROL/INTERFACE BASELINE; ACTUATOR SELECTION, FUNCTIONAL SAFETY, PROOF/JAM/ENDURANCE TESTS OPEN |
| MECH27 | two full-system 48 V 400 W-class drive envelopes, 33.5 Nm calculated torque, 40/80 Nm continuous/peak allocation, 30 Nm fail-safe brakes and transport/arm interlock | ANALYTICAL DRIVE BASELINE; MOTOR/GEARBOX/BRAKE/CONTROLLER/WHEEL/LOAD-EQUALIZATION SELECTION AND PHYSICAL TEST OPEN |
| MECH20 | drivetrain concept pair map, explicit XYZ axes, lateral rolling-vector check, motor-to-rear-hub interface deltas and reaction-load path | INTERFACE/KINEMATIC BASELINE COMPLETE; SHAFT/HUB/TRANSMISSION/LOAD/PHYSICAL VALIDATION OPEN |

## Assembly and tolerance datums

- Datum A: top face of lower chassis at Z=26 mm; flatness 0.30 mm.
- Datum B: chassis longitudinal centre plane (X=0); motor axes symmetric within 0.25 mm.
- Datum C: front display plane; display opening positional tolerance 0.30 mm to B.
- General prototype tolerance: ISO 2768-m; printed parts +/-0.30 mm.
- Injection shell wall 2.5 +/-0.20 mm, draft 1.5 deg minimum, rib thickness 0.55-0.65 times wall.
- Harnesses use 6 mm minimum bend radius for signal wiring and 20 mm for the 48 V trunk.
- Datum D: traction motor envelope centres at X = -88/+88 mm, Y = 0 mm; outboard motor-face datums are X = -112/+112 mm. These are reserved centres pending approved shaft and mount geometry.
- Datum E: driver-childboard envelope centre [0, 54, 151] mm; reserve +Z removal and +Y rear connector access until the physical service trial closes. Its provisional support plate is at Z=136 mm, with lower posts to the electronics-tray top at Z=102 mm.
- Datum F: battery reservation centre [0, 0, 52] mm; keep a 20 mm analytical heat-source gap and reserve a removable BMS/impact restraint until pack selection.
- Datum G: conventional chassis axes use X lateral and Y longitudinal; wheel
  centres are X = +/-105 mm and Y = +/-90 mm (track 210 mm, wheelbase 180 mm).
  Wheel axles, motor outputs and rear hubs are lateral along X. At the floor,
  nominal -X angular velocity crossed with -Z radial direction produces -Y
  forward velocity. Traction concept pairs `traction_motor_left ->
  wheel_rear_left` and `traction_motor_right -> wheel_rear_right`; motor-face
  origins are [-112, 0, 49] and [112, 0, 49] mm, with nominal interface deltas
  [7, 90, -6] and [-7, 90, -6] mm. These are review datums, not a frozen shaft
  or transmission design.
- Datum H: the enclosure depth is 244 mm to reserve a nominal 4 mm wheel-shell
  radial gap at the +/-90 mm wheelbase datums. The wheel envelope may extend
  5 mm nominal (6 mm allocated maximum) beyond the 220 mm chassis plate into the compliant bumper; mount-hole
  to wheel and chassis-edge ligaments are checked analytically and remain
  subject to physical tolerance-stack evidence.
