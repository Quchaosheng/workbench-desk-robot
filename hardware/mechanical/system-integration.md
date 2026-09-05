# Revision D system integration

This document controls the current Revision D mobile household manipulator. The
earlier 55 kg dual-arm workbench and two-wheel/four-caster planning cases are
obsolete and must not be used for purchasing, stability, harness, or assembly
decisions.

## Controlled configuration

- 540 x 520 mm navigation base with four independent 140 mm steer-drive modules.
- 1100 mm stowed height and 1450 mm raised height with 350 mm lift travel.
- Four stowed/deployed stabilizers; the raised concept STEP represents an
  820 x 820 mm support polygon.
- Two seven-axis arm envelopes with internal cable routing and one coordinated
  shared bimanual workspace.
- 48 V battery and high-power branches separated from controller J2 auxiliary
  power.

`design-spec.json#components` is the sole source for the `REV-D-MASS-001`
analytical mass model. `generated/analysis.json` records its source hashes,
revision, derived load cases, and center of gravity. `mass-ledger.csv` is a
validated mirror, while `mass-ledger-legacy.csv` retains the superseded 55 kg
planning baseline with explicit mappings and `EXCLUDED` inclusion rules. Any
duplicate, missing, non-finite, negative, unit-mismatched, frame-mismatched, or
stale row fails closed. All values remain estimates until a serialized assembly
is weighed and its center of gravity is measured.

## Stability and motion clearance

The navigation load case uses the lift lowered, tools stowed, brakes available,
and stabilizers retracted. The manipulation load case uses the lift raised,
bimanual payload forward, wheel brakes applied, and all four stabilizers loaded.
Both cases must include manufacturing tolerance, floor friction, joint
calibration error, stop distance, cable stiffness, payload overhang, and battery
configuration before release.

The analytical tip-angle formula is
`degrees(atan2(support_margin_mm, cg_z_mm - ground_plane_z_mm))`. Results are
published for +X, -X, +Y, and -Y against the explicit rectangular drive and
deployed-stabilizer support polygons; each result names its limiting edge and
pose identifier. The drive gate is the minimum across its stowed and emergency
stop cases. The stabilized gate is the minimum across raised, payload,
shared-workspace, and stabilizer-deployed cases. These thresholds are screening
gates, not safety functions.
Acceptance requires controlled pull, 5-degree slope, emergency-stop, brake-hold,
stabilizer-deployment, and first-wheel-lift tests. Any undocumented ballast,
tether, fixture, or operator restraint invalidates the result.

The motion envelope remains partitioned into left-only, right-only, coordinated
shared, and forbidden volumes. Review arm-to-arm, arm-to-base, arm-to-head,
arm-to-lift, tool-to-cable, payload-to-cover, and payload-to-operator clearance.
`interference-checklist.csv` remains `NOT_EXECUTED` until full-joint CAD sweeps
and guarded physical tests are attached.

## Assembly process

1. Verify base datums, steering retention, wheel bearings, suspension travel,
   normally-closed brakes, bumper and stabilizer pockets.
2. Install the battery, BMS, disconnect, fuse, precharge and contactors low in
   the base; record mass, location and mounting torque.
3. Install the lift guides, synchronized screws, brakes, lock pins, hard limits
   and pinch sensors; measure parallelism and skew before fitting the torso.
4. Install power distribution, safety controller, protective bonding and
   electronics tray before covers restrict access.
5. Mount both arm bases to controlled shoulder datums using a rated lift aid;
   manual handling outside the supplier limit is prohibited.
6. Route energy chains and internal joint harnesses through complete steering,
   lift and arm sweeps with strain-relief witness marks.
7. Install the neck mount, head, sensors, guards, E-stop devices and tools.
8. Execute bonding, power-off movement, interference, stability and guarded
   low-speed tests before enabling payload work.
9. Close covers, apply tamper marks, weigh the serialized unit and sign the
   assembly traveller.

Assembly feasibility gates include tool access, captive hardware, connector
keying, lift points, torque visibility, service loops, battery replacement,
controller replacement, sharp edges, pinch points, tolerance stack, coating
masks and packaging restraints.

Status: `CONCEPT_PHYSICAL_VALIDATION_REQUIRED`. The 77.5 kg analytical mass, calculated centers of gravity, directional tip angles, and STEP geometry are not measured product claims. Simulation or document-only evidence cannot close the physical release gate.
