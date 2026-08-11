# Risk management

[`risks.csv`](risks.csv) is the source of truth. This page defines how the register is reviewed and escalated.

## Scoring and response

| Probability / impact | Response |
|---|---|
| critical impact at any probability | review weekly; active owner and contingency required; blocks release while triggered |
| high probability and high impact | review weekly; mitigation due within seven days |
| medium | review at least monthly and at every phase gate |
| low | monitor; close only with evidence or an explicit acceptance decision |

Allowed status values are `open`, `mitigating`, `monitoring`, `accepted`, and `closed`. `accepted` requires a named human decision and expiry/review date. Closing a risk requires an evidence link; elapsed time alone is not evidence.

## Active release blockers

| Risk | Immediate mitigation | Escalation |
|---|---|---|
| R-001 | merge the least-privilege workflow fix after CI/review | no new tag until a human reviewer approves the fix |
| R-002 | freeze the formal Gazebo command and raw-log layout | P1 gate remains stopped without 36 eligible runs and independent audit |
| R-003 | resolve each hardware gate with physical/commercial evidence | keep `RELEASE_BLOCKED`; do not infer results from planning reports |
| R-004 | obtain quotes, AVL approval, and incoming inspection | keep `ORDER_RELEASE_BLOCKED` |
| R-005 | schedule three unique external participants | remove external reproducibility claims if records remain absent |
| R-007 | enforce same-PR schema/model updates, three-owner review, and contract validation | reject the change before merge if any owner or consumer is missing |
| R-009 | add continuous code/dependency review and triage policy | unresolved high/critical findings block release |

## Weekly review procedure

1. Check every trigger against the latest eligible evidence.
2. Confirm owner, next review date, mitigation progress, and contingency readiness.
3. Add new risks before discussing schedule optimism.
4. Record any acceptance, closure, or scope change in the decision log.
5. Update the status dashboard only after the register and evidence agree.
