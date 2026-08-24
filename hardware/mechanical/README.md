# Mechanical engineering package

This directory is the source-controlled mechanical baseline for the desk robot.
Dimensions are millimetres and mass values are kilograms. Revision B keeps the
280 x 240 x 330 mm envelope but turns the toy-like box into a product-shaped
desktop mobile robot: a low chassis, a drafted shoulder shell, a separate 8 deg
head module, recessed display bezel, hidden wheel pods, four corner bumpers, a
rear service panel, and a protected neck cable channel.

## Industrial design and CMF

The consumer-facing surface is a continuous warm-white shell with hidden primary
parting lines. The structural waist and arm links use bead-blasted dark natural
anodized aluminium; the face is a single smoked strengthened-glass lens; the
parcel-bay/acoustic insert is graphite 3D-knit recycled PET. Jade is reserved for
status light and gripper touch points. Visible glossy plastic, exposed fasteners,
painted faux-metal finishes, and decorative color blocking are out of scope.

## Reproduce

```bash
python hardware/mechanical/tools/generate_artifacts.py
```

The command validates clearances and writes the reports. When CadQuery 2.5 or
newer is installed it also regenerates the solid STEP file; otherwise the checked-in
STEP remains unchanged.

- `generated/enclosure.step`: AP203 STEP envelope for supplier exchange.
- `generated/desk_robot_assembly.step`: seven-solid assembly.
- `generated/desk_robot_exploded.step`: exploded assembly for work instructions.
- `generated/parts/*.step`: shell, chassis, tray, display bracket, bumper, and motor bracket.
- `generated/drawings/general-arrangement.svg`: dimensioned overall drawing.
- `generated/drawings/thermal-flow.svg`: inlet, heat source, conduction and outlet path.
- `generated/analysis.json`: mass, centre of gravity, tip angle, drop energy, and clearances.
- `generated/drop-screening.json`: equivalent-static impact screen and acceptance limits.
- `generated/assembly-sequence.json`: fastener and torque-controlled assembly order.
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
| Controller PCB / mount pattern | 160 x 130 / 152 x 122 mm |
| Estimated mass | 6.42 kg |
| Estimated CG from floor | 101.9 mm |
| Static tip angle | 45.9 deg |
| Target drop | 0.75 m onto plywood over concrete |

## Revision B mechanism decisions

- **Low visual mass:** the main chassis starts above the 18 mm ground-clearance
  plane; heavy battery and electronics remain below the shoulder datum.
- **Distinct head:** the 190 x 72 x 92 mm head is a separate service module at an
  8 deg datum, with a 3 mm display bezel and a 24 mm neck cable channel.
- **Protected mobility:** 50 mm wheels sit in recessed pods with a 3 mm guard
  clearance instead of exposed cylinders.
- **Controlled impact:** four compact TPU 95A corner pads replace the visually
  heavy full-perimeter orange bumper while retaining the 8 mm skin / 24 mm
  effective-stroke analytical gate.
- **Serviceability:** the rear 170 x 120 mm panel uses four captive M3 points and
  preserves the 20 mm rear clearance requirement.

The SCAD and CadQuery generator are now aligned to this Revision B structure.
The checked-in STEP remains an exchange artifact until CadQuery/SolidWorks
regeneration is available; no physical fit, drop, or appearance claim is made
from the digital model alone.

## Release status

MECH1-10 and MECH15 have reproducible design evidence in this package. MECH11-14
and MECH16 have controlled execution/acceptance definitions but require the actual
prototype, drop video, fit inspection, toolmaker data, and approved production BOM.
Generated analysis is not represented as physical test evidence.
The electronics tray now uses the controller PCB's actual 152 x 122 mm mounting
pattern and provides 60 x 40 mm total planar margin. Cable bend radius, connector
access and the 32 mm vertical envelope remain physical fit-check items. The digital
fit check also enforces 30 mm side and 20 mm front/rear service margins around the PCB.
