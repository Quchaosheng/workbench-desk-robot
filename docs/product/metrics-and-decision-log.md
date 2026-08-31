# Product Metrics and Decision Log

Metrics support decisions; they do not replace evidence. Use `UNKNOWN` when the
eligible source is missing. Never infer physical performance from scripts,
screenshots, or activity counts.

## Outcome metrics

| Metric | Definition | Minimum denominator / window | Eligible source | Gate use |
|---|---|---|---|---|
| External cold start | Unique external users reaching the documented first task from a clean environment | 3 unique participants per study window | Private participant record plus versioned artifact | Supports onboarding readiness |
| First-task completion | Users completing the declared task with required evidence | All eligible attempts in a declared window | Replayable run bundle and participant record | Supports product usability, not physical safety alone |
| Task verification rate | Confirmed outcomes / eligible task runs | All eligible runs for one scenario/version/window | Canonical WorldState and verifier output | Shared runtime quality signal |
| Insufficient-evidence rate | Runs unable to establish the goal state / eligible runs | Same denominator as verification rate | Event/evidence report | Drives instrumentation and UX work |
| Recovery success | Bounded recoveries reaching a newly evidenced valid state / recovery attempts | All recovery attempts in a declared window | Recovery events plus verification | Must not hide failed attempts |
| Time to reproduce | Time from feedback receipt to a deterministic reproduction | Each closed feedback record; report median and P95 | Feedback record and test artifact | Engineering support efficiency |
| Repeated problem count | Distinct participants with the same problem card | Count independent participants, not messages | Anonymized research records | Promotion signal for roadmap |
| Design Partner continuation | Partners completing the agreed test and choosing a next step | All partners whose test window ended | Scenario record and follow-up decision | Product/market signal |

## Activity metrics (diagnostic only)

Messages, meetings, demos, stars, forks, content posts, and contact-list size
can explain reach, but cannot prove user value or readiness. Track them only with
source and time period.

## Funnel entry criteria

Use explicit stage transitions instead of "interested" as a catch-all:

`discovered -> contacted -> replied -> interviewed -> high_match -> demo -> trial -> first_task -> design_partner -> procurement -> paused/lost`

An entry transition needs a dated record and next owner. For example, `trial`
requires a named tester, known environment, declared task, test window, and
installation material; a verbal “we can try it” is not enough.

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
- Review status: `open` / `accepted` / `rejected` / `deferred`:

## Weekly review questions

1. What user evidence changed our understanding this week?
2. Which problem is repeated across independent participants?
3. Which scenario can be tested with a bounded, measurable task?
4. Where is evidence insufficient or incorrectly classified?
5. What will we stop, defer, or explicitly not build?
