# Controller PCB engineering package

Six-layer controller/power-distribution board for a 48 V desk robot. The package
defines the electrical architecture, interfaces, protection, isolated CAN,
stackup, placement/thermal constraints, DFM limits, and manufacturing outputs.

## Reproduce checks

```bash
python hardware/pcb/tools/electrical_checks.py
```

The report is written to `generated/electrical_report.json`. Open
`kicad/controller.kicad_pro` with KiCad 10. The generated EVT companion board has
21 footprints/interfaces, 174 routed track segments across six copper layers, four
M3 mounting holes, and a physical 8 mm isolation-barrier region. Reproduce it with:

```bash
<kicad>/bin/python hardware/pcb/tools/generate_kicad_board.py
python hardware/pcb/tools/export_fabrication.py
```

The checked-in ERC and DRC reports contain zero violations and zero unconnected
items. Gerbers, drills, IPC-D-356, position data, drawings, statistics, and a
rendered inspection preview are under `fabrication/`.

## Critical design-review correction

The original task suggestion (`TPS54160 + RT8059 + AMS1117`) is not load-capable:

- TPS54160 is a 1.5 A regulator and cannot supply the proposed 12 V motor rail.
- RT8059 is a low-current converter and cannot supply a 5 V / 8 A Jetson rail.
- AMS1117 cannot provide 3.3 V / 5 A and would exceed its thermal limit.

The baseline therefore uses a protected 48 V input, an isolated 48-to-12 V
240 W module, a protected 12 V / 5 A branch to the Jetson developer-kit DC
input, and a 12-to-3.3 V 20 W synchronous buck. It deliberately does not
back-power the developer kit through a 5 V header. Design candidates are listed
in the fabrication BOM; purchase
requires the system owner's AVL sign-off because component selection is outside
issue #19's ownership boundary.

The board is a companion/control board for the NVIDIA developer kit, not a raw
260-pin Jetson module carrier. See `interface-control.md` and
`source-baseline.json` for controlled interfaces, official sources, assumptions,
owners, and freeze gates. J4 is populated on this board; J7-J9 describe downstream
harness or daughterboard endpoints and are not populated in revision A.
The ISO1042 bus side uses distinct `5V_CAN_ISO` and `GND_CAN_ISO` nets supplied
by U7; neither is tied to logic ground in the board database.
The E-stop path now has distinct `MOTOR_ENABLE_REQ` and `MOTOR_ENABLE_SAFE`
nets, a dual-channel J10 loop, a U8 safety-gate carrier, and J11 gated output.
`connector-pinout.csv` freezes the current EVT pin mapping.
`component-selection-matrix.csv` tracks every active module, the source-backed
candidate or class, verification method, owner and procurement status.

Run `python hardware/pcb/tools/release_readiness.py` before sharing an order
package. It intentionally reports `ORDER_RELEASE_BLOCKED` until the component-level
schematic, AVL, physical bring-up, safety analysis, and supplier DFM gates close.

## Release status

PCB1-11 have reproducible engineering evidence. PCB12-18 have complete order,
bring-up, reliability, and production procedures but still require physical boards,
lab instruments, EMC facilities, and production operators; see the verification
matrix for the evidence that must be attached rather than inferred.
