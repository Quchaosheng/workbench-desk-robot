# Product Evidence Layer

This directory is the product-management and user-evidence layer for Workbench.
It complements the engineering evidence chain; it does not replace the shared
runtime, Scenario Registry, Event Store, verifier, replay, or release gates.

## Operating principle

```text
user problem -> real task -> scenario contract -> implementation
             -> evidence -> verification -> product decision
```

Every proposed scenario should answer two separate questions:

1. Is this a real and repeated user problem?
2. Can the runtime prove the task outcome without confusing an action claim with observed state?

## Documents

- [Product brief](product-brief.md): current hypotheses, target users, jobs, non-goals, and validation plan.
- [90-day execution](90-day-plan.md): an evidence-gated operating cadence adapted from the product-manager plan.
- [Problem card template](problem-card-template.md): turn interviews into traceable problem evidence.
- [Design Partner scenario template](design-partner-scenario-template.md): define a bounded real-task collaboration.
- [Feedback record template](feedback-record-template.md): make external installation and trial failures reproducible.
- [Metrics and decision log](metrics-and-decision-log.md): distinguish activity metrics from product and evidence outcomes.

## Evidence and privacy boundary

The repository may contain only anonymized participant IDs, organization type,
scenario IDs, redacted problem statements, and evidence references. Do not commit
names, email addresses, phone numbers, budgets, private logs, raw videos, access
tokens, or identifiable customer material. Keep those in an access-controlled
private system and link only to an opaque evidence reference.

User statements, product hypotheses, scripted fixtures, Gazebo evidence, and
physical evidence are different evidence classes. None of them may silently
upgrade another class. In particular, a scripted fixture remains
`release_eligible: false` unless the applicable release gate says otherwise.

## Ownership boundary

- Product owns the problem definition, user evidence, prioritization, and acceptance intent.
- Runtime and architecture owners decide shared contracts and safety boundaries.
- Task/scenario owners implement domain rules without duplicating shared verification or replay.
- Motion, Perception, Navigation, MCU, and hardware owners implement adapters and physical validation.
- The human Project Owner owns Go/No-Go, scope, release, and external claims.

## Related execution Issues

- Multi-scenario epic: [#309](https://github.com/Quchaosheng/workbench-desk-robot/issues/309)
- Contract and ownership: [#308](https://github.com/Quchaosheng/workbench-desk-robot/issues/308)
- Definition of Ready: [#310](https://github.com/Quchaosheng/workbench-desk-robot/issues/310)
- Capability matrix: [#311](https://github.com/Quchaosheng/workbench-desk-robot/issues/311)
- Phase gates: [#314](https://github.com/Quchaosheng/workbench-desk-robot/issues/314)

## Weekly review

The weekly product review should record only:

- new user evidence and the source reference;
- repeated problems and affected scenarios;
- decisions to start, change, defer, or reject work;
- external installation or task results;
- blocked evidence and the next owner/action/date.

Templates and verbal updates never move an engineering or release gate to green.
