# Mechanical verification matrix — Revision D

| Task | Evidence | Status / gate |
|---|---|---|
| MECH1 | Revision D SCAD, mobile base, lift, torso, head and dual 7R assembly STEP | ENGINEERING COMPLETE; CAD REGENERATION REQUIRED |
| MECH2 | `generated/bom.csv`, lift locks, brake and tool-datum parts | COMPLETE |
| MECH3 | 260 x 105 x 128 mm smoked-glass head, 228 x 92 rounded display, keyed neck register | COMPLETE |
| MECH4 | base, enclosed drive skirt, four stabilizers and 350 mm lift | ENGINEERING COMPLETE; PHYSICAL FIT REQUIRED |
| MECH5 | `drawings/thermal-flow.svg`, isolated electronics and food-tool heat zone | ENGINEERING COMPLETE; thermal test external |
| MECH6 | analysis and drop-screening JSON, 28 mm absorber, 20 g screen | SCREEN COMPLETE; nonlinear FEA/drop external |
| MECH7 | two sets of seven joint IDs/limits, shared workspace and exploded STEP | DIGITAL CHECK COMPLETE; guarded motion external |
| MECH8 | ten D revision part STEP files, SCAD source and BOM, including the neck mount | READY FOR PROTOTYPE QUOTE |
| MECH9 | quick-change tool interface, force/slip/tool-ID requirements | DIGITAL CHECK COMPLETE; tool tests external |
| MECH10 | CG, drive/stabilized tip screens and arm moment in `analysis.json` | ANALYTICAL PASS; not release evidence |
| MECH11 | lift dual encoders, brakes, lock pins, hard limits and pinch sensors | DESIGN COMPLETE; synchronization test required |
| MECH12 | parcel, cleaning and supervised induction task boundary | CONCEPT ONLY; physical validation required |
| MECH13 | CMF and concealed parting strategy in design spec | DESIGN COMPLETE; DFM and finish sample required |

## Assembly and tolerance datums

- Datum A: mobile-base top frame; flatness 0.30 mm.
- Datum B: lift-column centre plane; guide parallelism within 0.20 mm over travel.
- Datum C: left/right shoulder mounting plates; symmetry and arm-base position tolerance 0.30 mm to B.
- General prototype tolerance: ISO 2768-m; printed parts +/-0.30 mm.
- Lift guide/lock clearance, brake hold, synchronization error, pinch detection and
  emergency stop must be tested before powered payload work.
- Both primary arm sets use internal cables and controlled 4–6 mm shadow gaps. Tool
  surfaces use removable 316L/PEEK/silicone parts; open flame and hot-liquid carry
  remain prohibited.
