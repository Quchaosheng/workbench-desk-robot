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
