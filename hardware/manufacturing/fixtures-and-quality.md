# Fixtures, layout, and quality plan

## Fixture list

| ID | Fixture | Capability / acceptance | Calibration |
|---|---|---|---|
| FX-01 | Datum and motor alignment nest | motor axes +/-0.25 mm, chassis flatness 0.30 mm | annual + daily check piece |
| FX-02 | PCBA guarded power jig | 0-60 V/10 A current limit, Kelvin rail measurement, emergency disconnect | annual; daily self-test |
| FX-03 | CAN loop fixture | selectable dual 120 ohm termination, CAN FD error counters, shield check | annual; golden board daily |
| FX-04 | Isolation/ground-bond fixture | barrier resistance and 4-wire bond below 0.10 ohm | annual; zero before shift |
| FX-05 | E-stop exerciser | trip latency capture, latch/reset proof, dry-contact fault injection | six months; daily golden unit |
| FX-06 | Harness continuity bed | pin-to-pin, shorts, keying, 500 V insulation where approved | annual; check harness daily |
| FX-07 | Final functional cart | restrained wheels, thermal probes, camera, barcode, fixture controller | annual; golden unit daily |
| FX-08 | Packaging drop setup | ISTA-style corner/edge/face sequence with dummy instrumented unit | before validation campaign |

Fixture software must record its version and reject an unknown product revision.
Measurement uncertainty must be no more than 25% of the applicable tolerance.

## Quality gates

| Gate | Required checks | Reaction on failure |
|---|---|---|
| QG-01/02 | supplier lot, revision, quantity, damage, kit completeness | quarantine lot / correct kit |
| QG-03/04 | paste coverage, placement, oven profile | stop SMT, clean/reprint or MRB |
| QG-05 | AOI plus polarity and isolation barrier | defect code, controlled rework, re-AOI |
| QG-06 | shorts, rail accuracy/ripple, input current, CAN, isolation | guarded power-off, MRB, full retest |
| QG-07/08 | alignment, torque, board clearance, protective bond | disassemble/rework, repeat gate |
| QG-09/10 | continuity, latch, strain relief, routing, gaps, vents | harness/shell rework, repeat inspection |
| QG-11 | E-stop trip, latch and deliberate reset | line stop and safety-owner escalation |
| QG-12 | interfaces, interlocks, 30-minute thermal soak | defect isolation, repair, full test restart |
| QG-13/14 | traveller closure, labels, cosmetics, pack contents | correct before release |

## Line layout

Material flows one way in a U-shaped cell: receiving supermarket -> ESD SMT/PCBA
area -> guarded electrical test -> mechanical benches -> safety/functional enclosure
-> final inspection -> clean packing. MRB/quarantine is physically fenced beside
inspection and never lies on the forward material path. Battery charging and storage
use a fire-rated cabinet away from exits. Minimum aisle is 1.2 m; the E-stop and
disconnect at powered test remain reachable without entering the guarded zone.

At the 10-minute bottleneck the theoretical output is 48 units/shift. Pilot planning
uses 70% availability and 85% first-pass yield: 28.6 good units/shift before learning
curve and material losses. Actual labour and yield replace these planning assumptions
after the 20-unit pilot.
