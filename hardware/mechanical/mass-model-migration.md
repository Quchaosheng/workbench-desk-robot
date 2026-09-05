# Revision D mass-model migration

`REV-D-MASS-001` is the authoritative Revision D analytical model. It is
defined in `design-spec.json#components`; generated reports derive totals and
centers of gravity from that source and bind the result with a SHA-256 hash.

The earlier seven-row, 55 kg planning ledger is preserved in
`mass-ledger-legacy.csv`. Every legacy row is marked `SUPERSEDED`, mapped to a
current stable component ID when it represents a component, and marked
`EXCLUDED`. It must not be used for
stability, payload, lift, drop, procurement, or release decisions.

The pre-baseline generated `63.5 kg` aggregate and its `[-24.1, 441.6] mm`
center of gravity are preserved as a superseded summary row in the same file;
the current `77.5 kg` model is the only Revision D release input.

The current nine-row `mass-ledger.csv` is a review mirror only. Its IDs,
coordinates, units, frame, masses, uncertainty, revision, and inclusion rules
are checked against the authoritative source. A mismatch, duplicate, missing
row, or stale generated hash blocks readiness.

The four owner approvals are recorded in `mass-model-approval-register.csv`.
They remain `REQUIRED` until Product, Mechanical, Hardware, and Safety owners
sign the controlled revision; analytical estimates do not constitute approval
or physical validation.
