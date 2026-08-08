# Rework, EHS, and packaging controls

## Nonconforming product and rework

1. Stop, label, and move the unit to MRB with its serial, operation, defect code,
   photo, suspected cause, and last passing gate. Never continue downstream testing.
2. MRB chooses use-as-is, rework, repair, return, or scrap. Safety, isolation,
   structural, and regulatory deviations cannot be accepted by production alone.
3. Rework uses a released instruction, trained operator, controlled tools, and one
   recorded cycle. A second cycle requires engineering approval; a third is prohibited.
4. After rework repeat the failed gate and every downstream gate. PCB heat rework
   triggers visual/AOI plus electrical retest; E-stop work triggers the complete safety test.
5. Trend defect Pareto daily during pilot. Three consecutive identical defects or
   any safety escape stops the line and opens corrective action.

## EHS rules

- ESD bench, grounded wrist strap, dissipative mat, ionizer where insulators cannot be removed.
- Powered tests use guarding, current limiting, insulated tools, and a visible emergency disconnect.
- Disconnect and verify zero energy before touching 48 V conductors; remove jewellery.
- Lithium battery lots remain in a fire-rated cabinet; swollen, hot, dropped, or damaged packs go to a fire-safe quarantine area.
- Solder extraction runs at the source. Operators follow paste/flux SDS, wash hands, and wear eye protection.
- Torque tools and presses use ergonomic supports; heavy cartons use team lift or a lift table.
- Keep aisles/exits clear. Log spills, near misses, shocks, burns, smoke, and battery events immediately.

## Packaging and transport validation

Fit wheel restraints and display protector, then place the robot in an EPE/EPP cradle
with at least 50 mm energy-absorbing material on every face. Bag accessories separately
so they cannot strike the product. Use double-wall carton, tamper seal, serial/carton
label, centre-of-gravity and orientation marks, and UN-compliant battery handling when
the battery ships installed.

Validation uses one instrumented production-equivalent pack: conditioning at low,
ambient, and high temperature; vibration profile for the selected transport mode;
then face, edge, and corner drops appropriate to package mass. Acceptance is no
safety defect, no functional failure, no connector loosening, no shell crack, display
damage, or packaging intrusion. Record acceleration, before/after photos, functional
test JSON, and packaging revision. A passed test applies only to that exact packaging revision.
