# Physical bench, bring-up, and debugging

Status: **NOT_EXECUTED**. This repository contains procedures and validators,
not a fabricated board or signed physical result.

## Required HIL bench

- isolated/current-limited 0-60 V supply rated for the intended load;
- two DMMs, four-channel oscilloscope, differential probe, current probe, and
  logic analyser with current calibration records;
- CAN-FD analyser, two controlled 120 Ohm terminations, known-good harnesses;
- dual-channel E-stop fixture, guarded load or disabled motor-driver fixture;
- thermal camera or bonded thermocouples, non-conductive mat, PPE, fire-safe
  isolation area, and a second person for the safety tests;
- Linux host with the intended CAN interface, camera, configuration hash, and
  synchronized UTC clock.

The board, harnesses, instruments, calibration references, operator, reviewer,
and raw capture directory must be identified before power is applied.

## Software preflight

The preflight only observes prerequisites; it sends no CAN or motion command:

```bash
python3 tools/scripts/hardware_preflight.py \
  --can-interface can0 --camera-device /dev/video0 \
  --output runs/hardware/preflight.json
```

`not_ready` is a stop. Create the E-stop marker only after the named operator
has physically verified both channels and the safe output with power removed.

## Staged bring-up

1. Record board serial/revision, BOM/PCB hashes, harness IDs, firmware/config
   SHA-256, operators, instruments, calibration records, ambient conditions and
   photos. Open a defect immediately for visible damage or a revision mismatch.
2. Execute steps 1-6 of `hardware/pcb/fabrication/bringup-test-plan.csv` with
   motor power disabled. Stop on current limit, smoke, heat, wrong rail order,
   excess ripple, isolation failure, or an unexpected enable.
3. Execute the J10/U8/J11 truth table, including each open channel and channel
   discrepancy. The 1 ms target needs an unedited logic-analyser capture.
4. Run CAN classic/FD loopback, then each populated J4 interface. Preserve raw
   frames and error counters; screenshots alone are insufficient.
5. Run the 30-minute rated-load thermal step. Proceed to first-batch and
   48-hour protocols only after QA and Safety owner review.
6. Run all 20 rows in `hardware/validation/fault-scenarios.csv`. A stopped or
   failed scenario stays `FAIL`/`HOLD`; it is not deleted and rerun as a new pass.

## Register evidence

First assign the real hardware revision and configuration hash to the unit in
`hardware/validation/first-batch-acceptance.csv`, then run:

```bash
python3 hardware/validation/tools/register_evidence.py \
  --evidence-id EVT-VAL5-01-001 --scenario-id VAL5-01 --unit-id UNIT-001 \
  --operator OPERATOR --reviewer REVIEWER --captured-at 2026-08-18T08:00:00Z \
  --evidence-kind physical --instrument-ref CAN-SCOPE-01 \
  --calibration-ref CAL-2026-001 --raw-file runs/hardware/val5-01.log \
  --result PASS

python3 hardware/validation/tools/validate_validation.py
python3 hardware/release/tools/check_release_readiness.py
```

The validator re-hashes raw files and derives scenario status. Editing a CSV
summary cannot create a pass.

## Debug decision tree

- **No input/current limit:** power off; inspect J1/F1/U1, polarity and
  VBAT-to-ground resistance. Never replace the fuse with a larger rating.
- **Missing/wrong rail:** disconnect J2/J3; work downstream from TP1 to TP5.
  Quarantine on isolation failure or unstable hot-swap cycling.
- **CAN offline/errors:** verify 5V/GND CAN isolation, CANH/CANL polarity,
  exactly two terminations, bit timing and shield policy before changing code.
- **J4 interface failure:** compare connector direction and frozen pin mux;
  capture reset, voltage and logic levels. Do not repurpose a safety pin.
- **Unexpected enable/E-stop failure:** remove power, quarantine immediately,
  attach the truth-table capture, and escalate to the Safety Owner.
- **Thermal fault:** stop load, retain current/temperature traces, inspect
  airflow and interfaces, and do not restart until disposition is signed.

For every observed failure add a row to `hardware/qa/defect-tracker.csv` with a
unique ID, serialized unit/lot, containment, evidence and owner. Leave root
cause/corrective action blank until verified; close only with linked retest
evidence. Missing equipment or an unbuilt board is a project blocker, not a
fabricated product defect.
