# Hardware release-readiness gate

This is the single release view for the engineering package. It joins the
existing PCB and manufacturing reports with the procurement, QA, and field
validation reports. A green engineering check does not release a physical
product: commercial, safety, laboratory, production, and field gates remain
blocked until dated evidence is attached.

The report exposes two independent stages. `EVT_PROTOTYPE_ORDER_*` covers the
engineering, owner, supplier, and design gates required before ordering a
prototype. `PRODUCTION_RELEASE_*` additionally requires physical bring-up,
measured safety timing, harness execution, and verified fixture access. This
separation prevents physical evidence from becoming a circular prerequisite for
the prototype that must generate it; neither stage is marked ready by a
repository-only validator when external evidence is absent.

Run:

```bash
python hardware/release/tools/check_release_readiness.py
```

The default command is a production-release gate and returns nonzero while
production is blocked. Use `--stage evt` for the EVT prototype-order gate or
`--stage structure` only when auditing the governance schema without requesting
a release decision. JSON-backed rows declare an `evidence_binding`; the checker
rejects a CSV `PASS` that disagrees with the bound engineering, EVT, production,
or physical-result field in the referenced report.

The command writes `generated/release_readiness_report.json`. Update
`evidence-register.csv` only with controlled records. Every external record must
identify the unit/lot, revision, operator, date, instrument or supplier source,
and a raw evidence path.

`hardware-closure-checklist.csv` is the machine-readable master list for the
axes, power, safety, PCB, harness, mechanical, validation, and compliance
owners. Its `evt_order_blocker` and `production_release_blocker` columns make
the stage boundary explicit while keeping all physical and commercial unknowns
fail-closed.
