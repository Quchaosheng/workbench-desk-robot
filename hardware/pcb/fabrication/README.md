# Fabrication release candidate

Generated with KiCad 10.0.5 from `kicad/controller.kicad_pcb`.

- `gerbers/`: six copper layers, solder mask, silkscreen, edge cuts, PTH/NPTH drill and maps.
- `controller.d356`: IPC-D-356 electrical netlist.
- `positions.csv`: component placement data.
- `drawings/assembly.pdf`: board assembly view.
- `drawings/controller-schematic.pdf`: controlled architecture schematic sheet.
- `board-stats.json`: machine-readable board statistics.
- `board-preview.png`: rendered board inspection image.

KiCad DRC and ERC reports are in `../generated/`; both contain zero violations.
This package is suitable for supplier DFM quotation and bare-board fabrication
review. Component purchase remains blocked until the system owner signs the AVL
candidate column in `bom.csv`; this respects issue #19's ownership boundary for
component selection.
