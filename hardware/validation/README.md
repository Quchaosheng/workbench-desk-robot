# Hardware field-validation package

This package is the handoff from simulation/engineering evidence to a real
machine. It does not claim that a robot, lab, or 48-hour run exists. Every
measurement template starts as `NOT_EXECUTED` and can only become `PASS` or
`FAIL` when a signed evidence record is attached.

- `sim2real-matrix.csv` defines the comparison dimensions and acceptance bands.
- `diagnostic-sop.md` is the operator decision tree for CAN, power, sensors,
  temperature and safe-stop faults.
- `fault-scenarios.csv` contains 20 fault-injection scenarios with recovery and
  evidence requirements.
- `first-batch-acceptance.csv` is the ten-unit acceptance template.
- `long-run-protocol.md` defines the 48-hour reliability run and stop rules.

Run `python hardware/validation/tools/validate_validation.py` to regenerate the
deterministic report.

## Evidence registration

First assign a real `hardware_revision` and 64-character configuration/firmware
hash to the unit in `first-batch-acceptance.csv`. Then register raw evidence:

```bash
python hardware/validation/tools/register_evidence.py \
  --evidence-id EVT-VAL5-01-001 --scenario-id VAL5-01 --unit-id UNIT-001 \
  --operator OPERATOR --reviewer REVIEWER --captured-at 2026-08-18T08:00:00Z \
  --evidence-kind physical --instrument-ref CAN-SCOPE-01 \
  --calibration-ref CAL-2026-001 --raw-file runs/hardware/val5-01.log --result PASS
```

The command stores SHA-256 hashes in `evidence-register.jsonl`. Validation fails
closed if a scenario or unit is unknown, a revision differs from the controlled
unit row, a file is missing or changed, or an evidence ID is reused. Editing a
summary CSV cannot promote a scenario to `PASS`.
