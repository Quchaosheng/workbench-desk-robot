# PCB verification matrix

| Task | Evidence | Status / gate |
|---|---|---|
| PCB1 | KiCad project, 110-symbol detailed schematic, routed EVT carrier, ERC report | ENGINEERING COMPLETE; component and safety approvals remain order gates |
| PCB2 | electrical spec, generated report, candidate BOM, official U2 exclusion evidence | BLOCKED: U2 MPN and land pattern are TBD; DCM3623T50M31C2T00 is excluded |
| PCB3 | 5 kVrms isolated CAN FD, U6 8.1 mm and U7 5.87 mm full-layer barriers, choke/TVS/termination plan | BLOCKED: U7 module safety suitability and surge test remain external |
| PCB4 | fuse, reverse protection, hot-swap UV/OV/inrush, E-stop sequence | DESIGN COMPLETE; bench trip-time test pending |
| PCB5 | `connectors.csv`, `connector-pinout.csv`, request/safe enable separation | EVT INTERFACE BASELINE COMPLETE; owner pin-mux sign-off required |
| PCB6 | eight-layer 160 x 130 mm board, 114 footprints, 1,250 track/via items, 31 copper zones, 8 SMT test pads, Gerber/drill/IPC-D-356 | CONCEPT DRC CLEAN; U2 footprint/placement/routing must be replaced by ECO after MPN freeze |
| PCB7 | 77-line grouped BOM, approval register and signed AVL/CTO gate | BLOCKED: all 68 controlled groups require approval; U2 remains a TBD requirement envelope |
| PCB8 | CAN rules, matched RAW blind-via transitions, graph metrics, reference-zone endpoint coverage, zero-via field routes and open-risk audit | DESIGN COMPLETE; uncovered reference bounds, coupling/stub review and fabricator impedance coupon remain open |
| PCB9 | thermal plan and acceptance limits | ANALYTICAL; U2 thermal model must be redone after MPN/land-pattern ECO, then chamber tested |
| PCB10 | pre-compliance plan | COMPLETE; lab scan required |
| PCB11 | fabrication directory with Gerber, drill, BOM, positions and drawings | COMPLETE |
| PCB12 | order package, DFM response fields and automated release audit | NOT ORDER READY; U2 MPN/land-pattern freeze plus approval, supplier, safety and physical gates remain open |
| PCB13 | 36/48/60 V rails, UV/OV/reverse/short/transient, E-stop/CAN captures, four-hour soak and controlled fixture-access plan | HOLD: seven test-access ECO pads and assembled prototype evidence required |
| PCB14 | pre-certification/certification report | HOLD: accredited lab required |
| PCB15 | signed ECN and production Gerbers | HOLD: PCB12-14 closure required |
| PCB16 | 20 assembled boards and AOI/X-ray record | HOLD: production required |
| PCB17 | temperature-cycle and vibration report | HOLD: test facilities required |
| PCB18 | controlled assembly, test, rework and evidence process | COMPLETE |
