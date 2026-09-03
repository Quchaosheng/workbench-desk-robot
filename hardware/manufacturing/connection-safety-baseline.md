# Connection Safety Baseline

Status: fail-closed wiring contract for the Revision D mechanical baseline. This
is an integration control document, not evidence that a harness has been built
or tested.

## Two power domains

The repository contains two deliberately separate motor paths:

1. **Revision D mobile robot:** 48 V battery -> protected traction branch -> four
   independent steer-drive modules. Each corner has a drive axis, steering axis,
   normally-closed brake and local feedback. This is the only current full-system
   traction architecture.
2. **Compact test chassis:** controller J2 12 V auxiliary -> traction childboard J_PWR -> candidate low-voltage brushed motors. This path is bench/test-only and is not allowed to drive the full-size chassis.

Never connect J2 to a 48 V motor, a full-system servo drive, or a battery branch. The current candidate dual-stall demand is 11 A while J2 is limited to 10 A; H02 therefore remains blocked and must not be used as a production power harness.

## Safety and diagnostics

- H07/H09 are dual-channel safety circuits only. They require independent channel continuity and cross-fault validation.
- H08/J11 is diagnostic-only. It must never be plugged into `J_SAFE`, bridged to a safety permissive, or used as a motor-enable source.
- H04/J4 remains blocked until a keyed shroud or connector ECO provides polarization and strain relief.
- H13/H14 remain blocked until the selected encoder voltage/output standard is recorded on the motor drawing and pinout.
- CAN shield drains terminate at the designated controller chassis entry only; do not bond isolated CAN signal return to chassis elsewhere.

## Energization gate

No battery, motor, lift, or arm energization is permitted until the exact mating parts are AVL-approved, the harness drawings are released, and serialized continuity, insulation, pull-force, installed-length, chafe, polarity, and emergency-stop tests are attached to the release evidence register.
