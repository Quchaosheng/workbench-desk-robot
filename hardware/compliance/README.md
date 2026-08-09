# Certification and regulatory evidence plan

Issue 26 controls CE, FCC, and UN 38.3 readiness. The repository makes no claim
that the product is certified. The responsible legal manufacturer and target
markets must be confirmed before the standards list and laboratory scope freeze.

## CE program

The technical file identifies the product, intended use, foreseeable misuse,
variants, drawings, BOM, risk assessment, applied standards, verification results,
labels, instructions, supplier evidence, and signed declaration. Determine the
applicability of EMC, Radio Equipment, Machinery, Low Voltage, RoHS, WEEE, and
battery obligations with a qualified compliance owner. An EU Declaration of
Conformity is signed only after applicable evidence is complete.

## FCC program

Classify intentional and unintentional radiators, radio modules, host integration,
antennas, cables, power supplies, and operating modes. Confirm whether supplier
module authorization can be used and meet its grant conditions. Pre-scan worst-case
modes before formal testing. FCC identifiers, statements, labeling, user instructions,
and Supplier's Declaration of Conformity responsibilities must match the final build.

## UN 38.3 and battery transport

Obtain the pack-level UN 38.3 test summary with manufacturer, model, mass, Wh,
test laboratory, report number/date, and completed T.1-T.8 applicability. Cell-only
evidence is insufficient for a separately designed pack. Maintain SDS, packaging,
state-of-charge, terminal protection, quantity, marking, documentation, carrier,
and damaged/defective battery rules for each transport mode.

## Before-order certificate gate

No affected PO is released until evidence for the exact MPN/revision is verified:

- battery pack and charger: UN 38.3 summary plus required safety/transport records;
- mains PSU/inlet/cable: market-appropriate safety approvals and ratings;
- radio module/antenna: grant/certificate and host-integration conditions;
- E-stop/safety relay: declaration, safety data, lifecycle, and application limits;
- flammability-critical polymer: material grade and lot-linked rating evidence;
- restricted substances: supplier declaration and, where risk warrants, test report.

Evidence checks compare manufacturer, MPN, revision, rating, factory/site where
relevant, issue/expiry date, report scope, and issuing body. Distributor web pages,
generic family certificates, draft reports, and cropped logos do not satisfy the gate.
Approved deviations require the compliance owner, project owner, expiry, containment,
and a documented route to closure; legal requirements cannot be waived internally.

## Formal test readiness

Freeze representative hardware, software/configuration, cables, peripherals,
radio settings, power supplies, and operating modes. Record serials and retain a
golden unit. Run worst-case functional modes, monitor safety, preserve lab data,
and control every modification after a failure. A passing pre-scan is engineering
evidence only. Final reports, declarations, labels, manuals, and change-control
assessment remain required before shipment.

Status: `NOT_CERTIFIED`. CE/FCC scope confirmation, supplier certificates,
pack-level UN 38.3 evidence, formal testing, and signed declarations are blockers.
