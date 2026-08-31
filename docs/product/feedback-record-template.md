# External Installation and Trial Feedback

Use one record per reproducible failure or meaningful success. Store raw logs,
screenshots, and videos privately; link them with an opaque evidence reference.

## Context

- Feedback ID:
- Participant/partner reference:
- Product version / commit:
- Scenario ID/version:
- Environment class:
- Evidence class: `user_report` / `software` / `scripted_fixture` / `gazebo` / `physical`
- Reporter role:
- OS and version:
- Hardware/model summary (redacted):
- Python / ROS version, if applicable:
- Date and duration:

## Reproduction

- Expected result:
- Actual result:
- Exact step where behavior diverged:
- Reproduction rate:
- Minimal reproduction command or procedure:
- Evidence reference:
- Related Event Store run/replay ID:
- Manifest/policy/verifier versions:

## Classification

- Category: `installation` / `compatibility` / `documentation` / `runtime` / `perception` / `motion` / `evidence` / `network` / `hardware` / `new_problem`
- Impact: `blocked` / `major` / `moderate` / `minor`
- Evidence status: `confirmed` / `refuted` / `insufficient_evidence` / `failed` / `not_executed` / `blocked`
- Temporary workaround:
- Suspected owner:
- Next action and due date:

## Resolution

- Root cause (after verification):
- Fix or documentation change:
- Verification command/result:
- User retest result:
- Linked Issue/PR:
- Follow-up decision:
- Release eligibility: `false` / `true` (include the applicable gate reference)

## Quality check

- [ ] Environment and version are recorded.
- [ ] Expected and actual results are separate.
- [ ] Raw evidence is referenced but not committed.
- [ ] The report does not confuse an ActionResult claim with observed WorldState.
- [ ] Failure remains visible if evidence is incomplete.
