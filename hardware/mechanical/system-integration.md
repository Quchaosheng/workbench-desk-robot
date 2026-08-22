# 55 kg system mechanical integration

This document controls the issue 21 design case without replacing the existing
6.42 kg enclosure model. The 55 kg value is the maximum configured system mass
for the dual-arm workbench including base, arms, payload, battery, electronics,
covers, and service accessories. It remains a planning case until a serialized
prototype is weighed and its centre of gravity is measured.

## Mass and centre of gravity

The mass ledger must sum to 55 kg or less and identify each item's measured or
estimated mass and XYZ location in the common base frame. Calculate centre of
gravity as `sum(mass * position) / sum(mass)` for each axis. Evaluate the worst
combination of both arms, rated payloads, moving cables, open service panels,
and removable battery. The release record includes the ledger revision and the
arm poses that produce the maximum overturning moment.

Acceptance requires positive stability margin at the declared operating slope,
caster/brake configuration, and floor friction. Analytical stability does not
replace a controlled pull test. A load cell, tilt reference, arm joint telemetry,
and video must identify the first lift or slip event. Any undocumented ballast,
fixture, tether, or operator restraint invalidates the result.

## Dual-arm interference

The motion envelope is partitioned into left-only, right-only, shared handoff,
and forbidden service volumes. Review arm-to-arm, arm-to-base, arm-to-display,
tool-to-cable, payload-to-cover, and payload-to-operator clearances. CAD sweeps
must include manufacturing tolerance, joint calibration error, controller stop
distance, payload overhang, and cable bend radius.

The minimum analytical clearance is a design input, not a safety function.
Physical low-speed sweep tests start without payload, then use the maximum
bounding payload in guarded conditions. Shared-volume entry requires a single
coordinator; independent arm commands cannot simultaneously reserve the same
volume. Collision-model edits require repeat review and regression evidence.

## Assembly process

1. Receive the base frame and verify datums, flatness, brake function, and labels.
2. Install ballast/battery low in the base and record mass and mounting torque.
3. Fit power distribution and protective bonding before covers restrict access.
4. Mount left and right arm pedestals to controlled datums and record torque.
5. Install arms with a rated lift aid; manual handling of the full arm is prohibited.
6. Route energy chains with full-joint sweeps and strain-relief witness marks.
7. Install compute, display, sensors, guards, and E-stop devices.
8. Load configuration/calibration under the approved commissioning procedure.
9. Execute bond, power-off motion, interference, stability, and guarded motion tests.
10. Close covers, apply tamper marks, weigh the serialized unit, and sign traveller.

Assembly feasibility gates include tool access, captive hardware, connector
keying, lift points, two-person operations, rework access, torque visibility,
and replacement of the battery and controllers without removing either arm.
The supplier DFM review must close sharp-edge, pinch-point, tolerance-stack,
service-clearance, coating-mask, weld distortion, and packaging restraints.

Status: `PHYSICAL_VALIDATION_REQUIRED`. A 55 kg target is not a measured result;
release needs the signed mass ledger, CG/stability report, dual-arm sweep log,
assembly trial, and resolved DFM actions for the production revision.

The estimate is recorded in `mass-ledger.csv`; `interference-checklist.csv`
enumerates the CAD and guarded-test evidence still required.

## Chassis traction integration

The mobile chassis reserves two symmetric traction motor volumes, four wheel
volumes at the controlled wheelbase/track, and a separate field-replaceable
motor-driver childboard volume. These are maximum space claims
for integration studies, not selected component geometry. Both motor MPNs,
technology, gear ratio, shaft and mounting interface, mass, torque reaction, and
thermal boundary remain `TBD_NOT_SELECTED`. The childboard final outline,
connector faces, component height, retention hardware, mass, and cooling path
also remain TBD.

The two traction motors are distinct from the six UR5e joint motors. UR5e joints
remain connected to and controlled by the vendor controller cabinet; this
mechanical package does not create substitute motor, brake, gearbox, or arm-drive
mounting provisions.

### Reviewable traction drivetrain concept

The chassis frame uses X lateral and Y longitudinal coordinates. The current integration baseline assigns the left and right traction motors to
the rear left and rear right wheels respectively. This is a two-motor
differential-drive concept; the front wheels remain passive until a later
architecture change is approved. Motor output and rear hub axes are both
declared along chassis `+Y`, with nominal motor-output origins at `[-86, 36, 49]`
and `[86, 36, 49]` mm and rear hub datums at `[-105, 90, 43]` and `[105, 90, 43]`
mm. This gives a 210 mm X-axis track and 180 mm Y-axis wheelbase. Each side reserves an offset reduction/coupler or belt path, a supported
intermediate shaft, and an enclosed rotating-part guard. The reaction path is
motor face -> motor bracket -> lower chassis and hub bearing -> side support ->
lower chassis.

These are interface and review datums only. Motor shaft diameter, hub pilot and
bolt pattern, bearing arrangement, centre distance, ratio, guard geometry,
fastener stack, and reaction-load sizing remain `TBD`; `physical_validation` is
`NOT_EXECUTED`. The generated report checks that the pair map, axes, role split,
and nominal deltas are internally consistent without claiming a usable
transmission or a physical fit.

The reserved childboard volume sits above the controller service volume, retains
an upward extraction path, and leaves a rear connector corridor. Physical release
requires an approved motor and childboard, tolerance-stack review, bracket load
analysis, wheel/hub/tyre/bearing selection, wheel load and traction review,
fastener selection, harness bend/strain-relief review, guarded wheel sweep,
thermal testing, and a demonstrated service-removal trial. The analytical
clearances in `generated/analysis.json` are not measured results.

The battery is reserved as a low, central `80 x 100 x 40 mm` envelope at
`[0, 0, 52]` with a removable restraint and service disconnect still TBD. The
generator checks its analytical separation from motors, wheels, the controller
tray, and the traction childboard; impact retention, pack chemistry, BMS, and
thermal measurements remain release gates. The childboard is carried on a
separate provisional plate/standoff assembly rather than floating in the CAD
model. The lower standoffs now reach the electronics-tray top datum at Z=102 mm
and the upper standoffs reach the board bottom; the mount datum, shock retention,
and controller-board keepout remain release blockers.
