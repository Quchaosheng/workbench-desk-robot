# Recommended Hardware Selection Package - Revision D

Status: engineering recommendation for the Revision D four-module holonomic
robot. This document does not represent AVL approval, a supplier quote, or
physical validation. Earlier two-wheel/four-caster Rev B/Rev C assumptions are
obsolete and must not be used for purchasing or mechanical interfaces.

## Frozen geometry assumptions

- 540 x 520 mm navigation base, 1100 mm stowed height, and 1450 mm raised height.
- Four independent steer-drive modules, each with a 140 mm wheel, absolute
  steering encoder, drive encoder, normally-closed brake, and 30 mm suspension.
- Four deployable stabilizers form an 820 x 820 mm analytical support polygon
  for stationary manipulation; physical fit, load and stability tests remain open.
- Four guides and two synchronized screws provide 350 mm lift travel with two
  brakes, two lock pins, dual encoders, hard limits, and pinch detection.
- Two seven-axis arm envelopes follow the 720 mm design reach and pose-dependent
  payload limits in `hardware/mechanical/design-spec.json`.

## Recommended configuration

| Function | Recommended candidate | Quantity | Why this is the baseline | Must close before order |
|---|---|---:|---|---|
| Collaborative arm | Exact seven-axis collaborative arm TBD | 2 | Must satisfy the controlled 720 mm reach envelope, internal cable routing, reaction-load limits and independent safety interface | Exact revision, mass, base drawing, reaction loads, controller power, safety I/O and payload/reach curves |
| Lift mechanism | Dual-screw synchronized lift, exact actuators TBD | 1 system | Matches the Revision D four-guide/two-screw architecture without inventing a four-column supplier configuration | Actuator and screw ordering codes, synchronization, brake/lock design, limits, proof load and skew test |
| Steer-drive module | 48 V independent steer-and-drive module, exact motor/gearbox/brake/wheel stack TBD | 4 | Required by the four-module holonomic geometry and 140 mm wheel envelope | Drive and steering curves, shaft/bearing drawings, brake torque, 30 mm suspension, thermal duty and loaded floor test |
| Drive/steering controller | Dual-STO-capable servo controller or paired drives, exact variant TBD | 4 modules | Must coordinate one steering and one drive axis per corner and handle regeneration without relying on controller J2 | Motor matching, STO timing, brake control, regeneration clamp, CAN/fieldbus, EMC and thermal evidence |
| Battery | 16S LiFePO4 2 kWh pack with service disconnect | 1 | Lower fire risk than NMC while meeting the 48 V / 80 A continuous design target | Cell/BMS MPN, contactor/precharge, fuse, enclosure, charger and transport documents |
| BMS | Orion BMS 2, 16S configuration | 1 | CAN telemetry, current/temperature limits, contactor and precharge control | Exact harness, sensor set, fault matrix and pack supplier integration |
| Safety controller | Pilz PNOZmulti 2 PNOZ m B0 class | 1 | Clear separation of E-stop, lift locks, drive STO, brake and mode interlocks | PLr/SIL allocation, I/O schedule, reset behavior and signed safety analysis |
| 48 V to 12 V | Murata UWE-12/20-Q48N-C class | 1 | Isolated 240 W rail for Jetson and auxiliaries without putting traction current on controller J2 | Lifecycle, land pattern, derating, cooling and load test |
| CAN isolation | TI ISO1042DWR + isolated 5 V module | 2 buses | Reinforced CAN isolation and known automotive EMC patterns | Creepage, termination, surge/ESD and loaded isolation supply test |

## Cost controls

- Keep the 32,000 USD EVT ceiling and 17,200 USD 100-unit BOM target as planning targets, not claims; both are unquoted.
- Request three dated quotes for each high-cost item: arm, lift column, drive motor/drive, battery pack and safety controller.
- Prefer one arm supplier, one lift supplier and one steer-drive supplier for EVT to reduce integration risk; qualify alternates only after interface freeze.
- Do not substitute the compact DRV8962 childboard for the full-system servo drives.

## Release gates

This recommendation is still blocked by exact MPN/AVL approval, supplier drawings/DFM, safety-owner approval, harness release, physical stability/brake/thermal/EMC testing and guarded EVT bring-up. The fixed shape is not evidence that those gates are closed.
