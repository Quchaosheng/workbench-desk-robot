# Fabrication release candidate

Generated with KiCad 10.0.5 from `kicad/controller.kicad_pcb`.

- `gerbers/`: eight copper layers, solder paste, solder mask, silkscreen, edge cuts,
  PTH/NPTH drills, F.Cu-In1/In2/In3 blind/microvia drills, and maps.
- `controller.d356`: IPC-D-356 electrical netlist.
- `positions.csv`: component placement data.
- `drawings/assembly.pdf`: autoscaled fabrication/assembly view with pad outlines.
- `drawings/routing-review.pdf`: autoscaled top-copper and silkscreen review view.
- `drawings/controller-schematic.pdf`: controlled component-level schematic.
- `fabrication-notes.csv`: controlled board revision, finish, thickness, HDI,
  impedance, and U2 hold requirements.
- `board-stats.json`: machine-readable board statistics.
- `board-preview.png`: rendered board inspection image.

The nominal 1.60 mm build in `stackup.csv` comprises 1.18 mm of dielectric and
0.42 mm of copper, using 0.035 mm per ounce as the engineering estimate. The
controlled requirement is 1.60 +/- 0.16 mm for finished laminate and copper,
excluding solder mask. KiCad statistics therefore report 1.62 mm after adding
nominal 0.01 mm mask on each side. The supplier must replace the nominal
dielectric values with an available qualified material set, account for finished
copper and plating, and close the 120 ohm CAN geometry with a coupon; the
analytical thickness match does not close supplier DFM or impedance gates.

The controlled board revision is EVT1 and the surface finish is ENIG. These
values are embedded in the PCB title block and Gerber job metadata. They do not
waive the order-release gates or supplier CAM approval.

U3 uses a 3 x 3 array of 0.45/0.15 mm laser microvias from its exposed pad on
F.Cu to the In1.Cu ground reference. These nine vias require selective copper
filling, capping, and planarization; the board-level `filling no` and `capping
no` defaults apply only to ordinary vias and do not override FAB-003. The
supplier must approve registration, stencil aperture, and assembly voiding
controls before release. The 0.30 mm minimum drill elsewhere in this package is
the mechanical-drill limit and does not describe this HDI feature. U3.17/U3.18
fan out through four parallel 0.8/0.4 mm plated through vias to the Jetson 12 V
plane; the layout audit hard-gates both via structures.

U6 and U7 isolation corridors are rule areas on all eight copper layers. U6
provides 8.1 mm pad-edge copper clearance. U7 preserves the candidate footprint's
5.87 mm board gap, but the candidate module's 2 mm creepage/clearance and 200 Vrms
working rating remain an open safety and vendor gate.

KiCad DRC and ERC reports are in `../generated/`; both contain zero violations.
This package is suitable for supplier DFM quotation and bare-board fabrication
review. The 77 grouped BOM lines cover all 110 electrical components and the four
mounting holes. All 68 procurement-controlled groups remain blocked until the required
owners complete their independent `component-approval-signatures.csv` rows with
an MPN, datasheet revision, identity, date, and evidence bound to this BOM hash.

Do not place a PCB or assembly order from this directory. The schematic and PCB
are detailed engineering candidates, but U2 is a visible `DO NOT FIT` placeholder;
U2, RPL and SFM4 land patterns still need vendor drawing closure. Run
`python hardware/pcb/tools/release_readiness.py`;
the expected current result is `PRODUCTION_RELEASE_BLOCKED` with
`EVT_PROTOTYPE_ORDER_BLOCKED` nested beneath it. Human, supplier, U2/U7, and
test-access design gates block EVT ordering; physical bring-up and fixture evidence
remain downstream production gates.
