# Status understanding protocol

P1 acceptance requires at least four of five participants to correctly distinguish all four expression states and the three verification outcomes.

## Prompts

Show the dashboard at these replay positions without naming the expected state:

| Run / position | Expected interpretation |
|---|---|
| any run before event 0 | idle / waiting |
| `run-uncertain`, event 2 | thinking / task in progress |
| `run-uncertain`, event 5 | uncertain / cannot confirm because evidence is missing |
| `run-recovery`, event 4 | refuted / first attempt did not meet the goal |
| `run-confirmed`, event 5 | pleased / verifier confirmed the goal with evidence |
| `run-recovery`, event 8 | recovery succeeded, earlier failure remains in history |

Ask each participant what the robot knows, what it does not know, and whether the screen authorizes any physical control.

## Result sheet

| Participant | Idle | Thinking | Uncertain | Pleased | Refuted vs insufficient | Read-only boundary | Pass |
|---|---:|---:|---:|---:|---:|---:|---:|
| P1 | | | | | | | |
| P2 | | | | | | | |
| P3 | | | | | | | |
| P4 | | | | | | | |
| P5 | | | | | | | |

The test owner signs and attaches the completed sheet. Empty rows are deliberately not counted as passes.
