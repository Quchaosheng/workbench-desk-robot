# PCB verification matrix

| Task | Evidence | Status / gate |
|---|---|---|
| PCB1 | KiCad project, architecture sheet, routed EVT carrier, ERC report | ARCHITECTURE COMPLETE; component-level schematic is an order-release blocker |
| PCB2 | electrical spec, generated report, candidate BOM | ENGINEERING COMPLETE; AVL owner sign-off required |
| PCB3 | 5 kVrms isolated CAN FD, routed 8 mm barrier, choke/TVS/termination plan | ENGINEERING COMPLETE; surge test external |
| PCB4 | fuse, reverse protection, hot-swap UV/OV/inrush, E-stop sequence | DESIGN COMPLETE; bench trip-time test pending |
| PCB5 | `connectors.csv`, `connector-pinout.csv`, request/safe enable separation | EVT INTERFACE BASELINE COMPLETE; owner pin-mux sign-off required |
| PCB6 | six-layer 160 x 130 mm board, 29 footprints, 176 tracks, 8 SMT test pads, Gerber/drill/IPC-D-356 | COMPLETE; DRC 0/unconnected 0 |
| PCB7 | review checklist and signed AVL/CTO gate | PACKAGE COMPLETE; human review required |
| PCB8 | CAN rules, stackup and routed layers | DESIGN COMPLETE; fabricator impedance coupon external |
| PCB9 | thermal plan and acceptance limits | ANALYTICAL; chamber test required |
| PCB10 | pre-compliance plan | COMPLETE; lab scan required |
| PCB11 | fabrication directory with Gerber, drill, BOM, positions and drawings | COMPLETE |
| PCB12 | order package, DFM response fields and automated release audit | DFM QUOTE READY; ORDER RELEASE BLOCKED |
| PCB13 | rail, ripple, timing, SPI/CAN scope captures | HOLD: assembled prototype required |
| PCB14 | pre-certification/certification report | HOLD: accredited lab required |
| PCB15 | signed ECN and production Gerbers | HOLD: PCB12-14 closure required |
| PCB16 | 20 assembled boards and AOI/X-ray record | HOLD: production required |
| PCB17 | temperature-cycle and vibration report | HOLD: test facilities required |
| PCB18 | controlled assembly, test, rework and evidence process | COMPLETE |
