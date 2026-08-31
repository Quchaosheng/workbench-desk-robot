# 90-Day Product Execution Plan

This is an evidence-gated operating plan for Workbench. Dates are planning
targets, not evidence that a capability is complete. Engineering and physical
claims still follow the repository's release gates.

## Days 1-30: understand the user and problem

### Deliverables

- Product brief and current ICP/Persona/JTBD hypotheses.
- 8-10 documented interviews, with at least 3-5 repeated problem cards.
- Product walkthrough from clean checkout: install, doctor, list, scripted run, replay, and dashboard inspection.
- First product decision log with explicit assumptions and open questions.

### Exit evidence

- Every promoted problem has a source reference and falsification condition.
- At least one problem maps to an existing scenario and one is a candidate for a new scenario.
- The three most dangerous onboarding or task-completion blockers are named.

## Days 31-60: turn evidence into an executable slice

### Deliverables

- PRD or Task Packet for one bounded problem.
- Given/When/Then acceptance criteria, including failure and recovery behavior.
- Internal demo report and clean-machine cold-start record.
- Updated capability matrix and scenario evidence status.

### Exit evidence

- A user can identify the entry point and expected result without an engineer taking over the main steps.
- P0 acceptance criteria are complete; unverified claims remain visible.
- The slice resolves through the Scenario Registry and shared runtime boundaries.

## Days 61-90: external validation and decision

### Deliverables

- A bounded Design Partner test with a real task, named evaluator, test window, and success condition.
- Installation/trial feedback records with reproducible environment and version details.
- Release/readiness report linking user evidence to engineering evidence.
- Quarter review: continue, change, defer, or stop decisions.

### Exit evidence

- At least one external participant completes the declared task or produces a documented failure with sufficient evidence.
- No fixture, interview, or marketing metric is represented as physical validation.
- Every decision has an owner, next action, due date, and evidence reference.

## Mapping to engineering Issues

| Product activity | Engineering contract |
|---|---|
| Problem and scenario definition | #308, #311 |
| Ready-to-build packet and acceptance | #310 |
| Registry and existing task migration | #300, #301 |
| Evidence identity and replay | #302, #313 |
| Recovery and bounded failure handling | #305, #312 |
| New scenario validation | #306 |
| Quality and release decision | #304, #307, #314 |

## Weekly cadence

- Monday: choose one learning goal and one delivery goal.
- Tuesday-Wednesday: interviews, user observation, or trial follow-up.
- Thursday: convert evidence into problem cards, acceptance criteria, or Issue updates.
- Friday: review metrics, blockers, decisions, and next actions.

No activity metric (messages sent, meetings held, stars, or demos) substitutes
for a documented user outcome or reproducible engineering evidence.
