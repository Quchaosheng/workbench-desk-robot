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
| Motor auxiliary / J2 | 12 V, 120 W maximum aggregate | Motion owner must supply driver inrush, regeneration and fault-current limits |
| Jetson power / J3 | Protected 12 V, 5 A continuous; no 5 V back-powering | Verify harness polarity and developer-kit input compatibility against the purchased revision |
| Jetson control / J4 | 3.3 V SPI, I2C, UART, enable, six chip selects, E-stop sense and MCU reset | Freeze Jetson header mapping and CH32V307 pin mux in the detailed schematic |
| CAN / J5, J6 | ISO1042 class, CAN FD, distinct 5V_CAN_ISO/GND_CAN_ISO domain, 120 ohm switchable termination | Confirm connector, TVS, choke and U7 isolated-power MPN |
| E-stop / J10 | Hardwired active-low loop; MCU observes but cannot override | Safety owner must approve circuit and measured disable time |
| J7-J9 | Downstream harness/daughterboard endpoint definitions only | Not populated on this companion-board revision |
| PCB / tray | 160 x 130 x 1.6 mm; 152 x 122 mm M3 pattern; 220 x 170 mm tray | 60 x 40 mm total planar margin; verify connector bend radii and 32 mm vertical clearance |
| Display | 150 x 72 mm opening only | Select display and freeze outline, keep-outs, data and power before tooling |

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
