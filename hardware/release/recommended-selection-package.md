# Recommended Hardware Selection Package Rev B

Status: engineering recommendation for the fixed Rev C shape. This document does not represent AVL approval, a supplier quote, or physical validation.

## Frozen geometry assumptions

- Existing Rev C envelope and mounting interfaces remain unchanged.
- Four guided lifting columns, 350 mm stroke, 300 kg minimum static allocation per column.
- Two 200 mm driven wheels, four 125 mm support casters, and four deployable leveling outriggers.
- Two 7-axis arm envelopes with 300 x 300 x 25 mm S355 mounting plates.

## Recommended configuration

| Function | Recommended candidate | Quantity | Why this is the baseline | Must close before order |
|---|---|---:|---|---|
| Collaborative arm | Kassow KR810, exact purchased revision TBD | 2 | Native 7-DOF architecture, 850 mm class reach, collaborative torque sensing, fits the reserved 30 kg arm envelope | Supplier base drawing, reaction loads, controller power, safety I/O, payload/reach confirmation |
| Lift column | LINAK LC3 6000 N family, exact ordering code TBD | 4 | Self-locking screw-column family with brake and feedback options; matches the four-column frame | Ordering codes, synchronizer, limit/absolute feedback, mechanical lock, proof-load method |
| Drive motor/gearbox | Dunkermotoren BG75 + PLG75 brake/gearhead configuration, exact winding TBD | 2 | Industrial 48 V class, serviceable gearbox, encoder and fail-safe brake options; sized for 200 mm wheels | Supplier torque-speed curve, shaft/flange drawing, encoder, brake torque, thermal curve |
| Drive servo | Elmo Gold Twitter 80 V STO class, exact variant TBD | 2 | Regeneration handling, dual-channel STO option, CAN/EtherCAT ecosystem | Motor matching, STO timing, regen clamp, EMC and thermal evidence |
| Battery | 16S LiFePO4 2 kWh pack with service disconnect | 1 | Lower fire risk than NMC while meeting the 48 V / 80 A continuous design target | Cell/BMS MPN, contactor/precharge, fuse, enclosure, charger and transport documents |
| BMS | Orion BMS 2, 16S configuration | 1 | CAN telemetry, current/temperature limits, contactor and precharge control | Exact harness, sensor set, fault matrix and pack supplier integration |
| Safety controller | Pilz PNOZmulti 2 PNOZ m B0 class | 1 | Clear separation of E-stop, lift locks, drive STO, brake and mode interlocks | PLr/SIL allocation, I/O schedule, reset behavior and signed safety analysis |
| 48 V to 12 V | Murata UWE-12/20-Q48N-C class | 1 | Isolated 240 W rail for Jetson and auxiliaries without putting traction current on controller J2 | Lifecycle, land pattern, derating, cooling and load test |
| CAN isolation | TI ISO1042DWR + isolated 5 V module | 2 buses | Reinforced CAN isolation and known automotive EMC patterns | Creepage, termination, surge/ESD and loaded isolation supply test |

## Cost controls

- Keep the 30,000 USD EVT ceiling and 16,000 USD 100-unit BOM target as targets, not claims.
- Request three dated quotes for each high-cost item: arm, lift column, drive motor/drive, battery pack and safety controller.
- Prefer one arm supplier, one lift supplier and one drive supplier for EVT to reduce integration risk; qualify alternates only after interface freeze.
- Do not substitute the compact DRV8962 childboard for the full-system servo drives.

## Release gates

This recommendation is still blocked by exact MPN/AVL approval, supplier drawings/DFM, safety-owner approval, harness release, physical stability/brake/thermal/EMC testing and guarded EVT bring-up. The fixed shape is not evidence that those gates are closed.
