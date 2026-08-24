# Full-system mechanical interface control

This document controls the lifting chassis fabricated around two purchased
seven-axis arm assemblies. It does not authorize manufacture of an arm,
actuator, controller, caster, leveling foot, battery pack, or safety controller.

## Configuration boundary

- Configuration: `DUAL_7DOF_LIFTING_WORKBENCH_REV_C`.
- Transport envelope: 1240 x 840 x 750 mm with the platform at its lower limit,
  both arms stowed, payload removed, arm power disabled, and outriggers retracted.
- Operating deck range: Z = 750 to 1100 mm over a 350 mm controlled stroke.
  The modeled parked-arm envelope at maximum lift is 1320 x 1200 x 2450 mm; it
  is not the complete swept or safeguarding volume.
- Operating support: four deployed, locked, and loaded leveling outriggers at
  X = +/-600 mm and Y = +/-480 mm. Casters are transport-only supports.
- Arm bases at lower limit: `[-300, -150, 750]` and `[300, -150, 750]` mm.
  Both move with the platform. Nominal yaw is 20.6 and 159.4 degrees.
- The 280 x 244 x 330 mm compact enclosure remains a separate electronics and
  traction package; it is not the load-bearing dual-arm chassis.

## Lift architecture and interlocks

Four guided telescoping columns reserve synchronized self-locking screw
actuators, absolute position feedback, redundant upper/lower limits, and
positive mechanical locks at deck heights 750, 850, 950, and 1100 mm. The
maximum commanded platform speed is 20 mm/s and the analytical skew limit is
2 mm. These are design allocations, not verified actuator capability.

Lift enable requires all four feet to be deployed and load-proven, both arms
stowed and safety-disabled, payload removed, guards closed, and no active arm
motion. Arm motion requires lift stopped, brakes applied, all four mechanical
locks proved engaged, column skew within limit, and deck height valid. Loss of
feedback, disagreement between limits, excessive skew, lock disagreement, or
unexpected descent commands a controlled stop and prevents automatic restart.
Bellows/fixed guards cover every shear and pinch zone. A 450 mm flexible bond
braid and a lift energy chain maintain protective bonding and cable control
through the full stroke.

## Datums and mounting

| Datum | Definition | Fabrication allocation |
|---|---|---|
| A | Finished upper face of the moving deck | flatness 0.50 mm at every lock height |
| B | Chassis longitudinal centre plane X = 0 | arm-base symmetry +/-0.25 mm |
| C | Front deck edge Y = -400 | arm-base Y location +/-0.25 mm |
| D/E | Left/right undrilled plate centres | position +/-0.25 mm; normal to A within 0.20 deg |
| F | Deployed leveling-foot plane | four-pad coplanarity within 1.0 mm after setup |
| G | Four guided column axes | parallelism and diagonal equality per reviewed fabrication drawing |

Each 300 x 300 x 25 mm S355 arm plate stays undrilled. The reserved interface
screen assumes no more than a 180 x 180 mm pattern with 14 mm holes, leaving
53 mm analytical edge ligament. Hole count, pattern, pilot, fastener grade,
torque, locating method, and surface finish are released only from the approved
drawing and serial revision of the purchased seven-axis arm.

## Load path and stability case

Arm reactions pass through the dedicated adapter plates, local upper
crossmembers, moving frame, four inner guide columns and locks, fixed outer
columns, lower frame, deployed outriggers, and leveling feet. The deck skin,
actuator screws, controller cabinets, and caster brakes are not the sole
reaction path.

The maximum-lift mass ledger is an unmeasured 368 kg estimate with CG
`[0.0, -28.8, 751.0]` mm. A 1200 x 960 mm support polygon produces analytical
roll/pitch tip screens of 38.6/31.0 degrees. With a 1.5 allocation factor, the
two-caster case is 276.0 kg each and the three-foot/lift-actuator case is
184.0 kg each. Controlled minima are 300 kg per caster, leveling foot, and lift
actuator. These allocations do not replace arm reaction loads, asymmetric
dynamic cases, buckling/FEA, shock/fatigue analysis, or physical proof and pull
tests. The estimate is not a measured result.

Powered transport uses two separate 48 V, 400 W-class geared wheel modules; it
must not use controller J2 or the compact 12 V traction childboard. The screen
requires 33.5 Nm per wheel after design factor, 40 Nm continuous/80 Nm peak
specified torque, and a 30 Nm fail-safe brake against an 18.9 Nm calculated
requirement. Travel requires deck low, arms stowed and safety-disabled, and
outriggers retracted. Arm enable requires both brakes applied.

## Services and release evidence

Controller and battery bays retain independent +Y removal. Power and signal
routes preserve 50 mm separation, with 75 mm fixed and 120 mm moving bend
radii. Required service space is 600 mm front/sides and 700 mm rear.

Before fabrication, attach selected arm and lift-column drawings, reaction
loads, caster/foot/outrigger data, weld map, material certificates, fastener
schedule, reviewed static/fatigue/buckling FEA, functional-safety review, and
supplier DFM. Before motion enable, attach lift proof-load, single-fault descent,
brake/lock, limit, skew/jam, emergency-lowering, endurance, deck survey,
fastener torque, bond, measured mass/CG, maximum-height stability pull, guarded
14-joint dual-arm sweep, stop-distance, cable sweep, and service-removal
evidence. Every unexecuted item remains `NOT_EXECUTED`; generated STEP geometry
is not physical evidence.
