# Mechanical engineering package

This directory is the source-controlled mechanical baseline for the desk robot.
Dimensions are millimetres and mass values are kilograms. The design is a compact
two-piece enclosure around a 260 x 220 mm chassis with a removable 150 x 72 mm
face module, internal electronics tray, motor mounts, cable channels, and a
perimeter TPU impact bumper.

## Reproduce

```bash
python hardware/mechanical/tools/generate_artifacts.py
```

The command validates clearances and writes the reports. When CadQuery 2.5 or
newer is installed it also regenerates the solid STEP file; otherwise the checked-in
STEP remains unchanged.

- `generated/enclosure.step`: AP203 STEP envelope for supplier exchange.
- `generated/analysis.json`: mass, centre of gravity, tip angle, drop energy, and clearances.
- `generated/bom.csv`: mechanical material and standard-parts BOM.

Open `cad/desk_robot.scad` in OpenSCAD for the detailed, parameterized assembly.
Export individual parts as STL for prototype printing. The STEP envelope is an
interface model; production fillets, draft, ribs, bosses, and tooling splits
remain controlled by the injection-moulding supplier after DFM review.

## Design baseline

| Property | Value |
|---|---:|
| Overall envelope | 280 x 240 x 330 mm |
| Chassis wheelbase / track | 180 / 210 mm |
| Ground clearance | 18 mm |
| Shell nominal wall | 2.5 mm |
| Electronics tray | 220 x 170 mm |
| Estimated mass | 6.42 kg |
| Estimated CG from floor | 101.9 mm |
| Static tip angle | 45.9 deg |
| Target drop | 0.75 m onto plywood over concrete |

## Release status

MECH1-10 and MECH15 have design evidence in this package. MECH11-14 and MECH16
require the actual prototype, drop video, interference scan, toolmaker data, and
approved production BOM. These are deliberately marked `HOLD` in
`verification-matrix.md`; generated analysis is not a substitute for a physical test.
