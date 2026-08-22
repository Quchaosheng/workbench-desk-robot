# Hardware interface control document

Baseline: `WB1-HW-ICD-REV-A`, reviewed 2026-08-07. The machine-readable
source and assumption ledger is `source-baseline.json`. This document controls
the EVT envelope; it does not substitute for supplier drawings or physical test.

## System partition

The PCB is a companion controller and protected power-distribution board for a
Jetson Orin Nano developer kit. It is not a raw Jetson module carrier and does
not implement the 260-pin module connector. J3 supplies a protected 12 V branch
to the developer-kit DC input through a keyed harness. J4 is the populated
20-pin, 3.3 V Jetson-to-MCU control backplane.

## Controlled interfaces

| Interface | Controlled envelope | State before EVT order |
|---|---|---|
| Battery / J1 | 36-60 VDC, 8 A continuous, 10 A fuse; keyed 4-pin | Owner must confirm battery, fuse interrupt rating, mating connector and wire gauge |
| Motor auxiliary / J2 | 12 V, 120 W maximum aggregate (10 A controlled system limit; connector contacts are 16 A nominal) | Motion owner must supply driver inrush, regeneration and fault-current limits, plus an approved external branch fuse |
| Jetson power / J3 | Protected 12 V, 5 A continuous; no 5 V back-powering | Verify harness polarity and developer-kit input compatibility against the purchased revision |
| Jetson control / J4 | 3.3 V SPI, I2C, UART, `JETSON_ENABLE_REQ` into the MCU on pin 8, six chip selects, E-stop sense and MCU reset | Freeze Jetson header mapping and CH32V307 pin mux; `JETSON_ENABLE_REQ` must remain distinct from the MCU-generated `MOTOR_ENABLE_REQ` safety-chain input |
| CAN / J5, J6 | ISO1042 class, CAN FD, distinct 5V_CAN_ISO/GND_CAN_ISO domain, 120 ohm switchable termination | Confirm connector, TVS, choke and U7 isolated-power MPN |
| E-stop / J10 | Common protected 12 V source on pins 1/3 with independent channel A/B returns on pins 2/4 | Safety owner must approve circuit, diagnostic coverage and measured disable time |
| Manual reset / J12 | Independent channel A/B reset returns feeding K1/K2 coil paths | Approve monitored-reset behavior, reset device, harness and welded-contact response |
| Safety output / J11 | `MOTOR_ENABLE_SAFE`, E-stop sense, GND and 3.3 V; software request is a separate net | Freeze mating motor-driver safety interface and prove MCU cannot bypass K1/K2 |
| Traction childboard / H02 + H09-H14 | H02 maps controller J2 pins 1-4 one-for-one to childboard `J_PWR`; H09 maps the future `J10/K1/K2` safety ECO to `J_SAFE`; H10 isolated CAN to `J_CAN`; H11/H12 motor outputs to external M1/M2; H13/H14 encoder I/O to external M1/M2 encoders | `J_SAFE` is an ECO endpoint, not current J11; freeze external motor/encoder MPNs, connector pin maps, shield/drain terminations and harness evidence |
| J7-J9 | Downstream harness/daughterboard endpoint definitions only | Not populated on this companion-board revision |
| PCB / tray | 160 x 130 x 1.6 mm; 152 x 122 mm M3 pattern; 220 x 170 mm tray | 60 x 40 mm total planar margin; verify connector bend radii and 32 mm vertical clearance |
| Display | 150 x 72 mm opening only | Select display and freeze outline, keep-outs, data and power before tooling |

The required logical behavior of U8 is controlled by
`safety-gate-truth-table.csv`. It is a functional requirement, not a claim that
the current carrier has achieved a safety integrity level.

## Power cases

Electrical checks evaluate Jetson loads at 15 W, 25 W and a conservative 40 W
MAXN envelope at battery inputs of 36 V, 48 V and 60 V. The 12 V isolated source
also carries the 120 W motor-auxiliary envelope and the converted logic load.
All computed rails require at least 20 percent continuous-power headroom.

## Release gates

1. Electrical and procurement owners select orderable MPNs and approved alternates.
2. Detailed schematic review freezes connector pin numbers, MCU pin mux and safety logic.
3. Harness drawing freezes wire gauge, color, shielding, mating parts and labels.
4. Supplier confirms stackup, impedance, creepage, copper current capacity and panel rules.
5. EVT units pass bring-up, thermal, E-stop, inrush, CAN, EMC pre-scan and enclosure fit checks.

Until all five gates close, the package is EVT-reviewable and supplier-RFQ-ready,
but it is not a production release and does not claim physical validation.

The current J11 provides only one `MOTOR_ENABLE_SAFE` output plus `ESTOP_SENSE`;
it cannot be split into the two independent childboard channels. The controlled
traction safety harness therefore terminates at the future `J10/K1/K2` ECO
endpoint (`J_SAFE`) and must not be wired to J11. H02 remains the only shared
power path from controller J2 to the childboard and its four pins are mapped
one-for-one in `hardware/manufacturing/harness-spec.csv`.
