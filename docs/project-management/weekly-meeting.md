# Weekly delivery review

Timebox: 45 minutes. The meeting makes decisions and removes blockers; workstream narration belongs in the pre-read.

## Required pre-read

- updated [status dashboard](status.md) and [`risks.csv`](risks.csv);
- failed or newly passing check links tied to commits;
- milestone variance and capacity changes;
- decisions needed from the human Project Owner.

## Agenda

| Minutes | Topic | Required output |
|---:|---|---|
| 0-5 | gate and safety blockers | explicit Red/Amber/Green/Unknown state |
| 5-15 | critical-path milestones | variance, owner, recovery date |
| 15-25 | top risks and triggers | mitigation/contingency decision |
| 25-35 | cross-team dependencies and capacity | owner-to-owner handoff and due date |
| 35-42 | decisions | decision record or ADR owner |
| 42-45 | actions and read-back | owner, date, evidence expected |

## Minutes template

```text
Date / facilitator / attendees:
Baseline commit:
Gate state: P1 __ / P2 __ / P3 __

Evidence reviewed:
- claim:
  reference:
  eligible: yes/no and why:

Decisions:
- D-YYYY-NNN / decision / owner / date / affected risks:

Actions:
- A-YYYY-NNN / action / owner / due / acceptance evidence:

Escalations:
- risk / trigger / contingency / decision needed by:
```

No owner, due date, or acceptance evidence means the item is not an action. No eligible evidence means the status remains Amber, Red, or Unknown.

