# Controller PCB engineering package

Eight-layer controller/power-distribution board for a 48 V desk robot. The package
defines the electrical architecture, interfaces, protection, isolated CAN,
stackup, placement/thermal constraints, DFM limits, and manufacturing outputs.

## Reproduce checks

```bash
python hardware/pcb/tools/electrical_checks.py
```

The report is written to `generated/electrical_report.json`. Open
`kicad/controller.kicad_pro` with KiCad 10. The detailed EVT companion board has
110 controlled electrical components, four M3 NPTH mounting holes (114 total
footprints), eight SMT test pads, 1,250 track/via items, 30 filled copper zones,
eight copper layers, and a physical 8 mm primary/secondary isolation region.
Reproduce the controlled sources with:

```bash
<kicad>/bin/python hardware/pcb/tools/generate_footprints.py
python hardware/pcb/tools/generate_kicad_schematic.py
python hardware/pcb/tools/generate_expected_connectivity.py
python hardware/pcb/tools/generate_bom.py
<kicad>/bin/python hardware/pcb/tools/generate_kicad_board.py --session hardware/pcb/kicad/controller.ses
python hardware/pcb/tools/electrical_checks.py
python hardware/pcb/tools/audit_connectivity.py
python hardware/pcb/tools/layout_audit.py
python hardware/pcb/tools/export_fabrication.py
python hardware/pcb/tools/release_readiness.py
```

`kicad/controller.ses` is the checked Freerouting 2.3.0 routing session. The
board generator validates every footprint position against that session before
importing 1,039 routed segments and 137 vias. Deterministic cleanup and local
supplements produce the final 1,070 segments, 180 vias, and 30 copper zones. A
stale session cannot silently attach to moved footprints.

The layout audit hard-gates the current U2 `12V_ISO` source and `GND` return with
separate eight-via rings on 3 x 3, 1.5 mm-pitch grids around the THT pads. These
rings are a spatial and current-path concept check only: U2 remains
`TBD_36_60V_TO_12V_240W_ISOLATED`, with no frozen MPN or land pattern. The
selected converter requires an ECO that replaces the footprint and placement,
rebuilds routing and planes, reruns DRC/connectivity, and repeats the thermal
review. The audit also requires top-layer, zero-via
oscillator routing, matched CAN via counts, and an `In1.Cu` `GND_CAN_ISO` zone
declaration. U7 has an all-eight-layer no-track/no-via/no-pour corridor across
its 5.87 mm board pad gap; this preserves the available geometry but does not
repair the candidate module's 2 mm creepage/clearance or 200 Vrms working rating.
CAN coupling, branch/stub geometry, reference-plane continuity, and
120 ohm field solving remain explicit manual or supplier risks rather than being
inferred from aggregate route lengths.

Test access is separated by electrical domain: TP1 remains in the 48 V primary
region, TP2-TP5/TP8 are on the logic side, and TP6/TP7 sit beside the isolated
CAN connectors. This keeps secondary probes out of the primary test area and
avoids long CAN test stubs.

The checked-in ERC and DRC reports contain zero violations and zero unconnected
items. Gerbers, drills, IPC-D-356, position data, drawings, statistics, and a
rendered inspection preview are under `fabrication/`.
`kicad/controller.kicad_dru` enforces 8 mm copper clearance between the primary
48 V domain and every non-primary net; release readiness fails if this rule is
missing even when the base DRC report is otherwise clean.

## Critical design-review correction

The original task suggestion (`TPS54160 + RT8059 + AMS1117`) is not load-capable:

- TPS54160 is a 1.5 A regulator and cannot supply the proposed 12 V motor rail.
- RT8059 is a low-current converter and cannot supply a 5 V / 8 A Jetson rail.
- AMS1117 cannot provide 3.3 V / 5 A and would exceed its thermal limit.

The baseline therefore requires a protected 48 V input and an isolated,
regulated 36-60 V-to-12 V 240 W-class module, followed by a protected 12 V / 5 A
branch to the Jetson developer-kit DC
input, and a 12-to-3.3 V 20 W synchronous buck. It deliberately does not
back-power the developer kit through a 5 V header. Design candidates are listed
in the fabrication BOM; purchase
requires the system owner's AVL sign-off because component selection is outside
issue #19's ownership boundary.

U2 has no orderable design candidate. `DCM3623T50M31C2T00` is explicitly excluded: the
official Vicor PDF specifies 16-50 V input, 28 V output, and a nine-terminal
through-hole ChiP package, so it cannot meet the 36-60 V-to-12 V requirement and
its land pattern is incompatible with the checked layout. The Vicor source in
`source-baseline.json` is exclusion evidence only. Until a real MPN and vendor
land pattern are frozen, the checked schematic, BOM, PCB and routing session use
a consistent `NOT FOR PRODUCTION` placeholder that must not be assembled or ordered.

The board is a companion/control board for the NVIDIA developer kit, not a raw
260-pin Jetson module carrier. See `interface-control.md` and
`source-baseline.json` for controlled interfaces, official sources, assumptions,
owners, and freeze gates. J4 is populated on this board; J7-J9 describe downstream
harness or daughterboard endpoints and are not populated in revision A.
The ISO1042 bus side uses distinct `5V_CAN_ISO` and `GND_CAN_ISO` nets supplied
by U7; neither is tied to logic ground in the board database.
The populated J4 backplane carries the external `JETSON_ENABLE_REQ` on pin 8;
it is an MCU input and is deliberately distinct from the internal
`MOTOR_ENABLE_REQ` generated on U5 pin 53. The E-stop path has distinct
`MOTOR_ENABLE_REQ` and `MOTOR_ENABLE_SAFE` nets,
a dual-channel J10 loop, dual-channel manual reset at J12, diagnostic isolation
at U8, force-guided relay candidates K1/K2, and the J11 gated output.
`connector-pinout.csv` freezes the current EVT pin mapping.
`connectors.csv` separates contact capability from the controlled system
envelope: J2 contacts are a 16 A nominal interface, but the board and harness
are limited to 10 A aggregate (120 W at 12 V) until an external branch fuse,
inrush, regeneration and fault-current analysis is approved.
`component-selection-matrix.csv` tracks every active module, the source-backed
candidate or class, verification method, owner and procurement status.
`fabrication/bom.csv` contains 77 grouped lines covering every board component.
`component-approval-register.csv` contains owner and evidence slots for every
one of the 68 procurement-controlled groups; no row is treated as approved without a named MPN,
datasheet revision, approver, date, and evidence reference.
Changing `decision` to `APPROVED` is insufficient: an orderable MPN, datasheet
revision, named approver, date, and evidence reference are all required.
`expected-connectivity.json` and `generated/connectivity_report.json` independently
check 458 physical pads across all 110 controlled components, plus input-protection, CAN
isolation, current-sense and dual-channel safety invariants.
`testpoint-coverage.csv` defines the measurement, limit, instrument and required
evidence for every physical test pad.

Run `python hardware/pcb/tools/release_readiness.py` before sharing an order
package. The checked-in schematic is component-level (110 symbols and 366 wired
net labels) and has clean ERC. Order release still remains blocked until AVL,
physical bring-up, safety analysis, harness release and supplier DFM gates close.
The release audit also fails closed if the excluded U2 MPN or footprint appears
in any controlled schematic, PCB, library, routing, netlist, BOM or position
artifact, and it keeps
`isolated_power_mpn_and_land_pattern_frozen` false until the required ECO is
complete.
Do not order a populated board from engineering completeness alone.

## Release status

PCB1-11 have reproducible engineering evidence. PCB12-18 have complete order,
bring-up, reliability, and production procedures but still require physical boards,
lab instruments, EMC facilities, and production operators; see the verification
matrix for the evidence that must be attached rather than inferred.
