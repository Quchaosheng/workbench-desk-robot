# PCB verification matrix

| Task | Evidence | Status / gate |
|---|---|---|
| PCB1 | KiCad project skeleton, connectors, architecture | DESIGN BASELINE; symbol-level capture/ERC pending |
| PCB2 | `electrical-spec.json`, generated report, review correction | CALCULATION PASS; AVL HOLD |
| PCB3 | 5 kVrms isolated CAN FD, 8 mm barrier, choke/TVS/termination | DESIGN COMPLETE; surge test pending |
| PCB4 | fuse, reverse protection, hot-swap UV/OV/inrush, E-stop sequence | DESIGN COMPLETE; bench trip-time test pending |
| PCB5 | `connectors.csv`, routing rules | COMPLETE |
| PCB6 | six-layer stackup and board outline | ROUTING/DRC HOLD |
| PCB7 | CTO review comments | HOLD: reviewer required |
| PCB8 | controlled-net rules | HOLD: fabricator stackup and field solver required |
| PCB9 | thermal plan and acceptance limits | ANALYTICAL; chamber test required |
| PCB10 | pre-compliance plan | COMPLETE; lab scan required |
| PCB11 | release checklist | READY; exports require completed layout |
| PCB12 | purchase order, DFM response, board receipt | HOLD: supplier required |
| PCB13 | rail, ripple, timing, SPI/CAN scope captures | HOLD: assembled prototype required |
| PCB14 | pre-certification/certification report | HOLD: accredited lab required |
| PCB15 | signed ECN and production Gerbers | HOLD: PCB12-14 closure required |
| PCB16 | 20 assembled boards and AOI/X-ray record | HOLD: production required |
| PCB17 | temperature-cycle and vibration report | HOLD: test facilities required |
| PCB18 | manufacturing process is in `hardware/manufacturing/` | DRAFT COMPLETE |
