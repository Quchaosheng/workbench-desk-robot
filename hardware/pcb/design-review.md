# Electrical design review

## Architecture and protection sequence

```text
48 V battery
  -> 10 A fuse -> reverse-polarity MOSFET -> 58 V TVS
  -> hot-swap/inrush controller (UV 34 V, OV 62 V, 8 A limit)
  -> isolated 48-to-12 V / 240 W module
       -> protected 12 V motor auxiliary output
       -> protected 12 V / 5 A branch -> Jetson developer-kit DC input
       -> 3.3 V / 5 A synchronous buck -> MCU, sensors, isolated CAN logic

CH32V307 <-> reinforced digital isolation <-> CAN FD transceiver
Hardwired E-stop loop -> driver-enable gate; MCU only observes state
```

Power-good sequencing is `12V_ISO` then `JETSON_12V` then `3V3_LOGIC` with 10 ms
minimum spacing. Any input UV/OV, hot-swap fault, or E-stop assertion disables motor
driver enable within 1 ms while logic rails remain up long enough to record the fault.
Recovery from E-stop requires loop restoration plus a separate physical reset.

## Signal integrity and grounding

- L2 and L5 remain uninterrupted reference planes; no signal crosses a plane split.
- CANH/CANL are 100 ohm differential, length matched within 5 mm, with choke and TVS at connectors.
- SPI is source-terminated (22-33 ohm footprint), kept under 150 mm, and referenced to L2.
- ADC pairs route away from switch nodes; AGND joins ground at the ADC reference region.
- Isolation barrier has no copper or silkscreen crossing and maintains 8 mm creepage.
- Cable shield bonds to chassis through a 1 nF / 2 kV capacitor plus optional 1 Mohm bleed.

Controlled impedance values must be recalculated from the selected fabricator's
actual dielectric table. No generic trace width is released as an impedance guarantee.

## Thermal plan

The 15 W, 25 W and conservative 40 W Jetson load cases are external to this board;
the protected 12 V branch and harness are screened at 5 A continuous. The Jetson
thermal solution conducts to the chassis and is validated separately from the PCB.
Power stages use 2 oz copper on L1/L3/L4/L6, exposed-pad via arrays (0.30 mm drill,
1.0 mm pitch, filled/capped if required), and at least 900 mm2 copper per high-power
stage. Thermal acceptance is converter junction below 110 C and Jetson module below
80 C at 35 C ambient, measured with the production enclosure closed.

## EMI pre-compliance

- Common-mode input choke and pi-filter footprints are provisioned but populated only after LISN data.
- Keep switch-node copper on L1, minimal, with its return directly below on L2.
- Spread-spectrum mode is allowed only after CAN and ADC noise comparison.
- Pre-scan conducted emissions 150 kHz-30 MHz and radiated emissions 30 MHz-1 GHz.
- Test ESD at accessible connectors and EFT/burst on the battery input before certification.

## Fabrication and assembly release checklist

1. KiCad ERC has zero errors; all waivers are signed and included.
2. DRC uses 0.15 mm trace/space, 0.30 mm finished drill, 0.15 mm annular ring, and 8 mm barrier creepage.
3. Plot Gerber X2, Excellon PTH/NPTH, IPC-356 netlist, drill map, stackup, fab drawing, and board PDF.
4. Export BOM with manufacturer part numbers and AVL state; no `HOLD` line may be ordered.
5. Export centroid, assembly drawings, paste layers, and polarity drawing.
6. Independently compare Gerber-to-PCB nets and inspect all planes, clearances, labels, and pin 1 marks.
