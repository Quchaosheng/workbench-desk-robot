# Quality engineering package

This package defines how a real unit, PCB assembly, harness, and enclosure are
inspected and how failures are closed. It is a controlled test and evidence
plan, not a claim that physical units have already passed.

- `test-standard.md` defines functional, electrical, safety, workmanship and
  reliability gates.
- `inspection-plan.csv` maps each operation to a method, sample size, limit and
  evidence record.
- `fmea.csv` contains the initial failure-mode register and owners.
- `defect-workflow.md` and `defect-tracker.csv` define MRB, containment and
  corrective-action states.
- `aql-plan.csv` defines lot sampling and the zero-tolerance safety rules.
- `compliance-matrix.csv` tracks RoHS, EMC/FCC and battery evidence without
  asserting certification that has not been issued.

Run `python hardware/qa/tools/validate_qa.py` to regenerate the report.
