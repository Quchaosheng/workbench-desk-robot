# Legacy 55 kg dual-arm workbench integration

> **Scope note:** this document is retained for the earlier dual-arm workbench
> planning case. It does not describe the Revision C Workbench Home Robot,
> which is a single 7R arm on a 49.5 kg concept mobile base. Use
> `revision-c-architecture.md`, `design-spec.json`, and the C verification matrix
> for the current product direction.

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
