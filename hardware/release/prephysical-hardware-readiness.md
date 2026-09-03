# Pre-physical hardware readiness

This package controls every system-level decision that can be prepared before
serialized hardware exists. A candidate is not an approved AVL line, and no
supplier configuration, safety decision, FEA result, or measured performance is
inferred from a candidate name.

## Power boundaries

The main 48 V battery reservation is at least 2 kWh, 80 A continuous and 120 A
peak. High-power modes are mutually exclusive:

- `ARM_OPERATION`: arm controllers only; outriggers loaded, lift locked and
  drive brakes applied.
- `TRANSPORT`: four steer-drive modules only; deck low, arms stowed/disabled and
  outriggers retracted.
- `LIFT`: dual-screw lift only; arms disabled and drive brakes applied.

The controller PCB U2 240 W isolated rail powers Jetson, logic and low-power
auxiliaries only. It never powers the seven-axis arms, full-system traction or
lifting columns. Arm power is a separate branch and remains conditional on the
purchased controller input: native DC when supported, otherwise a reviewed
isolated inverter.

## Freeze sequence

1. Select the purchased seven-axis arm revision and collect base, load, power,
   safety and controller documents.
2. Freeze the dual-screw lift actuator ordering codes, four-guide interfaces and
   independent mechanical locks.
3. Match all four 48 V steer-drive motor, gearbox, brake, wheel, bearing,
   suspension and controller curves.
4. Select battery, BMS, contactors, fuse, precharge, disconnect and charger as
   one coordinated protection system.
5. Execute the controller U2 ECO only after its exact module drawing and thermal
   design are accepted.
6. Complete childboard schematic, regeneration, safety gates, layout and thermal
   design before promoting any candidate to an approved MPN.
7. Release harness drawings only after every mating connector and crimp tooling
   is confirmed against the purchased equipment.

The next physical stage supplies measured mass/CG, proof load, stability,
thermal, power transient, insulation, safety timing, harness pull/continuity,
collision, braking and endurance evidence. Until then the release status stays
blocked by design.
