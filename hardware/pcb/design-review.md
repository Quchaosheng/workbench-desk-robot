# Electrical design review

## Architecture and protection sequence

```text
48 V battery
  -> 10 A fuse -> reverse-polarity MOSFET -> 58 V TVS
  -> hot-swap/inrush controller (UV 34 V, OV 62 V, 8 A limit)
  -> TBD isolated regulated 36-60 V-to-12 V / 240 W-class module
       -> protected 12 V motor auxiliary output
       -> protected 12 V / 5 A branch -> Jetson developer-kit DC input
       -> 3.3 V / 5 A synchronous buck -> MCU, sensors, isolated CAN logic

CH32V307 <-> reinforced digital isolation <-> CAN FD transceiver
Dual-channel E-stop + manual reset -> K1/K2 force-guided relay candidates
  -> MOTOR_ENABLE_SAFE; U8 provides isolated channel diagnostics only
MCU supplies MOTOR_ENABLE_REQ and observes state but cannot bypass K1/K2
```

Power-good sequencing is `12V_ISO` then `JETSON_12V` then `3V3_LOGIC` with 10 ms
minimum spacing. The design target is for any input UV/OV, hot-swap fault,
channel discrepancy, or E-stop assertion to disable `MOTOR_ENABLE_SAFE` within
1 ms while logic rails remain up; instrumented trip-time evidence is still required.
Recovery from E-stop requires loop restoration plus a separate physical reset.
U8 remains an interface carrier: order release is blocked until the Safety Owner
freezes the safety architecture, diagnostic coverage, reset circuit, implementation,
and failure-mode analysis.

U2 is an unresolved requirement envelope, not a selected component.
`DCM3623T50M31C2T00` is excluded by its official datasheet because its 16-50 V
input, 28 V output and nine-terminal through-hole package do not satisfy this
design. The required U2 state is `TBD_36_60V_TO_12V_240W_ISOLATED`; both the
orderable MPN and vendor land pattern remain unfrozen.

## Signal integrity and grounding

- The eight-layer stack assigns L2/In1 and L5/In4 to ground-reference and
  low-speed routing duties. L7/In6 carries controlled logic and safety signals;
  L3/In2, L4/In3, and L6/In5 carry separated primary, protected-Jetson, logic,
  and isolated-CAN power distribution plus routed escape segments. The released
  Gerbers, rather than a generic layer label, are the source of truth for copper.
- CAN targets 120 ohm differential. `CANH_RAW/CANL_RAW` are top-layer,
  point-to-point routes using two matched F.Cu-to-In3.Cu blind vias per net,
  measuring 12.210/13.942 mm (1.732 mm aggregate delta). The field-side
  `CANH/CANL` trees are top-layer and zero-via, with 72.352/72.073 mm aggregate
  totals (0.279 mm delta); both
  nets branch to two connectors, protection, termination, and testpoints.
- The isolated CAN corridor declares an adjacent `GND_CAN_ISO` zone on `In1.Cu`.
  Pair coupling, stub geometry, branch correspondence, reference-plane
  continuity, supplier field solving, and an impedance coupon remain release gates.
- SPI series-termination footprints are populated; return-path geometry must be
  reviewed against the released Gerbers and the supplier's final stackup.
- The custom DRC rules enforce 8 mm copper clearance between primary and
  secondary domains. Finished-board creepage and contamination class still
  require supplier and safety review.
- U7's logic/field pad rows have a 5.87 mm board-copper gap protected by an
  all-eight-layer no-track/no-via/no-pour rule area. The MEJ1S0305SC candidate
  itself remains unsuitable evidence for reinforced isolation because its
  documented creepage/clearance is 2 mm and its working rating is 200 Vrms.

Controlled impedance values must be recalculated from the selected fabricator's
actual dielectric table. No generic trace width is released as an impedance guarantee.

## Thermal plan

The 15 W, 25 W and conservative 40 W Jetson load cases are external to this board;
the protected 12 V branch and harness are screened at 5 A continuous. The Jetson
thermal solution conducts to the chassis and is validated separately from the PCB.
Power distribution uses 2 oz copper on L1/L3/L6/L8. The current U2 concept has
separate eight-via source and return rings on 3 x 3, 1.5 mm-pitch grids around
the THT pads, using 0.8 mm vias with 0.4 mm drills. This geometry proves only
that a candidate current-transfer scheme
can fit; it is not a released footprint or thermal solution. After the real MPN
and land pattern are frozen, an ECO must redo the footprint, placement, routing,
planes, clearances, DRC, connectivity audit and thermal analysis. Filling or
capping remains subject to the selected assembly process. Copper-area adequacy is
a thermal-review item, not inferred from DRC. Thermal acceptance is converter
junction below 110 C and Jetson module below 80 C at 35 C ambient, measured with
the production enclosure closed.

U3's exposed pad has a 3 x 3, 0.4 mm-pitch array of 0.45/0.15 mm F.Cu-to-In1.Cu
laser microvias, offset 0.25 mm from pad center to clear the PGTH route. Its 5 A
output uses four parallel 0.8/0.4 mm plated through vias into the In3.Cu Jetson
plane. Laser-via fill, cap, planarization, registration, stencil aperture, and
voiding controls remain a supplier DFM gate rather than a DRC inference.

## EMI pre-compliance

- The CAN common-mode choke and TVS are placed before the field connectors.
- Any input-filter change driven by LISN data requires an ECO and renewed DRC/thermal review.
- Keep switch-node copper on L1, minimal, with its return directly below on L2.
- Any spread-spectrum mode is allowed only after CAN and power-rail noise comparison.
- Pre-scan conducted emissions 150 kHz-30 MHz and radiated emissions 30 MHz-1 GHz.
- Test ESD at accessible connectors and EFT/burst on the battery input before certification.

## Fabrication and assembly release checklist

1. KiCad ERC has zero errors; all waivers are signed and included.
2. DRC uses 0.15 mm trace/space, 0.30 mm finished drill, 0.15 mm annular ring, and 8 mm barrier creepage.
3. Plot Gerber X2, Excellon PTH/NPTH, IPC-356 netlist, drill map, stackup, fab drawing, and board PDF.
4. Export BOM with manufacturer part numbers and AVL state; no `HOLD` line may be ordered.
5. Export centroid, assembly drawings, paste layers, and polarity drawing.
6. Independently compare Gerber-to-PCB nets and inspect all planes, clearances, labels, and pin 1 marks.
7. Freeze the U2 orderable MPN and vendor land pattern, complete its layout/thermal ECO, and prove the excluded DCM3623 data is absent from every released artifact.
