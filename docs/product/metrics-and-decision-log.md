# Product Metrics and Decision Log

Metrics support decisions; they do not replace evidence. Use `UNKNOWN` when the
eligible source is missing. Never infer physical performance from scripts,
screenshots, or activity counts.

## Outcome metrics

| Metric | Definition | Eligible source | Gate use |
|---|---|---|---|
| External cold start | Unique external users reaching the documented first task from a clean environment | Private participant record plus versioned artifact | Supports onboarding readiness |
| First-task completion | Users completing the declared task with required evidence | Replayable run bundle and participant record | Supports product usability, not physical safety alone |
| Task verification rate | Confirmed outcomes / eligible task runs | Canonical WorldState and verifier output | Shared runtime quality signal |
| Insufficient-evidence rate | Runs unable to establish the goal state | Event/evidence report | Drives instrumentation and UX work |
| Recovery success | Bounded recoveries that reach a newly evidenced valid state | Recovery events plus verification | Must not hide failed attempts |
| Time to reproduce | Time from feedback receipt to a deterministic reproduction | Feedback record and test artifact | Engineering support efficiency |
| Repeated problem count | Distinct participants with the same problem card | Anonymized research records | Promotion signal for roadmap |
| Design Partner continuation | Partners completing the agreed test and choosing a next step | Scenario record and follow-up decision | Product/market signal |

## Activity metrics (diagnostic only)

Messages, meetings, demos, stars, forks, content posts, and contact-list size
can explain reach, but cannot prove user value or readiness. Track them only with
source and time period.

## Decision log entry

For each material product decision, record:

- Decision ID and date:
- Decision owner and reviewers:
- Context and user problem:
- Evidence references:
- Options considered:
- Decision and rationale:
- Scope and non-goals:
- Risks and assumptions:
- Next validation:
- Revisit date or trigger:
- Linked Issue/PR/release report:

## Weekly review questions

1. What user evidence changed our understanding this week?
2. Which problem is repeated across independent participants?
3. Which scenario can be tested with a bounded, measurable task?
4. Where is evidence insufficient or incorrectly classified?
5. What will we stop, defer, or explicitly not build?
