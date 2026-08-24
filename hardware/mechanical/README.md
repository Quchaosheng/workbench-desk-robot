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
`TBD` and must not be ordered from this package. The fourteen joints in the two
seven-axis arms remain inside their vendor arm/controller systems and are
outside this traction design.

## Reproduce

```bash
python hardware/mechanical/tools/generate_artifacts.py
python hardware/mechanical/tools/generate_full_system.py
```

The command validates clearances and writes the reports. When CadQuery 2.5 or
newer is installed it also regenerates the solid STEP file; otherwise the checked-in
STEP remains unchanged.

The second command generates the load-bearing, height-adjustable full-size
dual-seven-axis workbench.
Its source is `full-system-structure.json`, with a separate conservative mass
ledger in `full-system-mass-ledger.csv` and controlled datums in
`full-system-interface-control.md`. This resolves the previous scale mismatch:
the compact enclosure remains a subsystem, while the dual arms mount to a
1200 x 800 mm structural frame at a 750 mm deck height.

- `generated/full_system/full_system_assembly.step`: complete structural and
  supplier-envelope assembly.
- `generated/full_system/full_system_exploded.step`: separated service and
  installation view.
- `generated/full_system/parts/*.step`: welded frame, deck, two arm plates,
  battery tray, cable management, casters, leveling feet, and bumper.
- `generated/full_system/envelopes/*.step`: two vendor arm, two controller,
  and battery/ballast reserved envelopes.
- `generated/full_system/analysis.json`: mass/CG, support polygon, tip angles,
  mount geometry, component separation, and load allocations.
- `generated/full_system/drawings/general-arrangement.svg`: top/side interface
  drawing; supplier envelopes remain visibly marked as TBD.

- `generated/enclosure.step`: AP203 STEP envelope for supplier exchange.
- `generated/desk_robot_assembly.step`: reproducible seventeen-solid assembly including eight named TBD envelopes and the childboard support.
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
| Overall envelope | 280 x 244 x 330 mm |
| Chassis wheelbase / track | 180 mm along Y / 210 mm along X |
| Wheel space claim | 4 x diameter 50 x width 12 mm; lateral X axles; contact Z=18 mm |
| Ground clearance | 18 mm |
| Shell nominal wall | 2.5 mm |
| Electronics tray | 220 x 170 x 3 mm; top datum Z=102 mm |
| Controller PCB / mount pattern | 160 x 130 / 152 x 122 mm |
| Traction motor space claim | 2 x 48 x 72 x 46 mm; left/right centres X = -88/+88 mm |
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
therefore track is 210 mm and wheelbase is 180 mm. Wheel axles are lateral
along X, so nominal rear-wheel angular velocity `-X` crossed with the ground
radial direction `-Z` produces forward velocity along `-Y`. The generated STEP
and SCAD models use the same axis mapping. Motor brackets sit on the lower-chassis top
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
rear hub axes are lateral along chassis `+X`; each motor face is outboard and
each side reserves an offset motor-to-hub transmission path and a supported
hub/bearing interface. The front wheels remain passive support concepts until
the caster/roller geometry is selected. Shaft diameter, pilot, bolt pattern,
reduction ratio, intermediate shaft, guard, and reaction-load sizing remain
`TBD` and `NOT_EXECUTED` for physical validation.

The chassis mount pattern is 242 x 205 mm. Four local X-axis cylindrical wheel-well cuts remove the tyre/chassis intersection. The nominal wheel-well model reserves 4 mm side/radial clearance, a 5 mm
longitudinal wheel overhang (6 mm allocated maximum) into the compliant bumper, and 3 mm minimum
mount-hole ligament. These are tolerance allocations, not measured fit
evidence; the guarded wheel sweep and physical tolerance stack remain open.

The 6.42 kg compact enclosure analysis is intentionally separate from the
55 kg dual-arm workbench design case in `mass-ledger.csv`. Neither mass, CG,
or stability result is a measured release result.

The new full-system structural baseline supersedes the 55 kg planning case for
mechanical sizing. Its conservative maximum-height ledger is 368 kg, including
two 30 kg seven-axis arm allowances, two 7 kg payload cases, controllers,
battery/ballast, fixed chassis, four-column lifting structure, deck, guards and
harness allowance. The deck operates from 750 to 1100 mm only on four deployed
leveling outriggers; lift motion disables both arms, and arm motion requires the
platform mechanical locks to be proved engaged.

Two independent 48 V, 400 W-class geared drive modules with fail-safe brakes
are reserved for full-system transport. The compact 12 V Pololu/DRV8962 package
is an electronics and traction experiment only and cannot propel the 368 kg
full-size chassis. Full-system travel is limited to 0.3 m/s with platform low,
arms stowed/disabled and outriggers retracted; arm enable requires drive brakes.

The 55 kg ledger is retained only because the existing operations-readiness
contract references that historical planning
case; it must not be used to size the new frame, casters, feet or stability test.
