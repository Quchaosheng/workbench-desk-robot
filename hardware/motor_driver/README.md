# Dual-axis traction childboard engineering package

This package defines a reviewable, independently replaceable controller for two
chassis traction motors. It does not control the six UR5e joints or the Robotiq
gripper; those remain on their vendor controllers.

The selected review baseline is two 12 V brushed-DC gearmotors powered from the
controller PCB's J2 auxiliary output. One `DRV8962DDVR` is the driver candidate,
not an approved part. Pololu item 4753 is now a traceable motor candidate (12 V,
50:1 gearbox, 64 CPR encoder); it is not an approved AVL selection. Its
datasheet-reported/extrapolated 5.5 A stall current would be about 11 A for two
motors, above J2's 10 A aggregate ceiling. A bounded current-limit, stall and
motion-profile policy is therefore required before this candidate can proceed.
The production motor MPN, final winding envelope, wheel load and thermal duty
remain open. Consequently this package is `DO_NOT_ORDER` even when its
deterministic engineering checks pass.

## Partition and power path

```text
controller J2, 12 V / 120 W aggregate maximum
  -> childboard branch protection and reverse-polarity protection (TBD)
  -> local bulk plus approved regenerative-energy sink (TBD)
  -> DRV8962 four half-bridges
  -> left and right brushed motors (MPNs and envelopes TBD)

isolated CAN field bus -> isolated CAN interface -> local traction controller
dual hardwired safety channels -> independent nSLEEP and EN gating
```

J2's 120 W limit is a shared input ceiling, not a per-axis rating. At 12 V it is
10 A aggregate before harness drop, conversion loss, transient margin and
temperature derating. The DRV8962 datasheet's 10 A-per-output DDV capability is
also an IC limit, not a board, connector, motor or simultaneous two-axis rating.

The isolated 12 V converter is not assumed to absorb regenerative current. A
motor can raise the local bus during deceleration or back-driving, so an approved
combination of blocking, bulk capacitance, clamp/brake switch and energy sink is
required before a schematic may be released. The protected 48 V traction bus is
retained as an alternative in `architecture-options.csv`; it remains blocked on
the battery maximum, surge/regen envelope, motor selection and a suitable power
stage.

The childboard must not join `GND_CAN_ISO` to `GND_MOTOR`. Its CAN interface
therefore requires an isolated CAN FD transceiver and isolated-side power; J_CAN
pin 4 remains `NC`, matching controller J5/J6. Cable shield termination is a
separate chassis/EMC decision and is not assigned to that reserved pin.

## Safety invariant

Software may request torque but cannot create safety permission. Channel A must
hardware-gate `nSLEEP`; channel B must independently gate all four `ENx` paths.
Opening either channel disables both bridges and latches the discrepancy until
the upstream manual-reset sequence is complete. `MOTOR_ENABLE_REQ`, CAN traffic,
MCU GPIO and a watchdog cannot bypass either gate.

The current controller J11 exposes one `MOTOR_ENABLE_SAFE` output plus the
diagnostic `ESTOP_SENSE`. Splitting the one safe signal, or treating
`ESTOP_SENSE` as the second channel, is forbidden. An owner-approved controller
and harness ECO providing two independent safety outputs is therefore a release
blocker.

## Layout concept

`placement-plan.csv` is a functional-block placement, not a land-pattern
definition. Run the deterministic renderer to update the review drawing:

```bash
python hardware/motor_driver/tools/generate_layout_review.py
```

The concept keeps the input protection and energy-management loop at the power
connector, the driver central, motor connectors at the opposite edge, and the
CAN/control and safety blocks away from the switching-current loop. Exact board
dimensions, copper weight, driver land pattern, heatsink attachment, creepage,
connector footprints and mounting pattern remain blocking inputs.

## Reproduce checks

```bash
python hardware/motor_driver/tools/validate_motor_driver.py
python -m pytest tests/hardware/test_motor_driver_package.py -v
```

Passing these checks means the package is internally consistent and fail-closed.
It never substitutes for a clean detailed ERC/DRC, approved AVL, supplier DFM,
safety review, calibrated waveforms, dyno data or physical thermal validation.
