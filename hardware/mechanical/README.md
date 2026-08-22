# Mechanical engineering package

This directory is the source-controlled mechanical baseline for the desk robot.
Dimensions are millimetres and mass values are kilograms. The design is a compact
two-piece enclosure around a 260 x 220 mm chassis with a removable 150 x 72 mm
face module, internal electronics tray, motor mounts, four wheel envelopes, cable channels, and a
perimeter TPU impact bumper.

The traction addition is a controlled space reservation, not a selected motor
design. It models two chassis traction motor envelopes, four wheel envelopes,
and one independently replaceable driver-childboard envelope. Motor technology,
MPN, shaft, mount, wheel/hub/tyre hardware, mass, loads, connector locations, board outline, and thermal solution remain
`TBD` and must not be ordered from this package. The six UR5e joint motors remain
inside the vendor arm/controller system and are outside this traction design.

## Reproduce

```bash
python hardware/mechanical/tools/generate_artifacts.py
```

The command validates clearances and writes the reports. When CadQuery 2.5 or
newer is installed it also regenerates the solid STEP file; otherwise the checked-in
STEP remains unchanged.

- `generated/enclosure.step`: AP203 STEP envelope for supplier exchange.
- `generated/desk_robot_assembly.step`: seventeen-solid assembly including eight translucent TBD envelopes and the childboard support.
- `generated/desk_robot_exploded.step`: exploded assembly for work instructions.
- `generated/parts/*.step`: eight part STEP files covering shell, chassis, tray,
  display bracket, bumper, motor bracket, childboard support plate, and
  childboard standoffs.
- `generated/envelopes/*.step`: left/right traction motor, four wheel, battery, and driver-childboard reserved envelopes.
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
| Chassis wheelbase / track | 180 mm along Y / 210 mm along X |
| Wheel space claim | 4 x diameter 50 x width 12 mm; contact Z=18 mm |
| Ground clearance | 18 mm |
| Shell nominal wall | 2.5 mm |
| Electronics tray | 220 x 170 x 3 mm; top datum Z=102 mm |
| Controller PCB / mount pattern | 160 x 130 / 152 x 122 mm |
| Traction motor space claim | 2 x 48 x 72 x 46 mm; left/right centres X = -86/+86 mm |
| Driver childboard space claim | 118 x 82 x 20 mm; centre [0, 54, 151] mm |
| Battery reservation | 80 x 100 x 40 mm; centre [0, 0, 52] mm; restraint TBD |
| Childboard service reservation | 35 mm upward removal; 20 mm rear connector corridor |
| Estimated mass | 6.42 kg |
| Estimated CG from floor | 97.9 mm |
| Static tip angle | 42.6 deg conservative (roll 47.0 / pitch 42.6) |
| Target drop | 0.75 m onto plywood over concrete |

## Release status

MECH1-10 and MECH15 have reproducible design evidence in this package. MECH11-14
and MECH16 have controlled execution/acceptance definitions but require the actual
prototype, drop video, fit inspection, toolmaker data, and approved production BOM.
Generated analysis is not represented as physical test evidence.
The electronics tray now uses the controller PCB's actual 152 x 122 mm mounting
pattern and provides 60 x 40 mm total planar margin. Cable bend radius, connector
access and the 32 mm vertical envelope remain physical fit-check items. The digital
fit check also enforces 30 mm side and 20 mm front/rear service margins around the PCB.

The chassis datum is conventional XYZ: X is lateral left/right and Y is
longitudinal front/rear. Wheel centres are X = +/-105 mm and Y = +/-90 mm;
therefore track is 210 mm and wheelbase is 180 mm. The generated STEP and SCAD
models use the same axis mapping. Motor brackets sit on the lower-chassis top
datum (Z=26 mm), and the childboard support has lower posts to the tray top
datum (Z=102 mm); both contacts are checked by the generator.

The traction geometry checks only prove that the provisional envelopes fit the
digital chassis model. Release remains blocked until approved motors and wheel
assemblies are inside the reserved envelopes, wheel load/traction/sweep are validated,
the reserved envelope, mounting and shaft interfaces are frozen, reaction loads
and bracket stiffness are verified, the childboard outline/connectors/thermal
solution are frozen, and a guarded physical fit plus harness sweep is executed.

The current drivetrain is a reviewable concept only: two independent motors are
assigned to the rear left/right wheels for differential drive. Motor outputs and
rear hub axes are parallel to chassis `+Y`; each side reserves an offset
motor-to-hub transmission path and a supported hub/bearing interface. Shaft
diameter, pilot, bolt pattern, reduction ratio, intermediate shaft, guard, and
reaction-load sizing remain `TBD` and `NOT_EXECUTED` for physical validation.
