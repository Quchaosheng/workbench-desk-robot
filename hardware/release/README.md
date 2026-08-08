# Hardware release-readiness gate

This is the single release view for the engineering package. It joins the
existing PCB and manufacturing reports with the procurement, QA, and field
validation reports. A green engineering check does not release a physical
product: commercial, safety, laboratory, production, and field gates remain
blocked until dated evidence is attached.

Run:

```bash
python hardware/release/tools/check_release_readiness.py
```

The command writes `generated/release_readiness_report.json`. Update
`evidence-register.csv` only with controlled records. Every external record must
identify the unit/lot, revision, operator, date, instrument or supplier source,
and a raw evidence path.
