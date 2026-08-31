# Design Partner Scenario Record

This record defines a bounded collaboration around a real task. It is not a
free custom-development agreement and does not grant a partner or scenario
authority over safety, release, or shared runtime contracts.

## Partner and scope

- Partner reference (opaque):
- Organization type:
- Primary evaluator role:
- Scenario ID/version:
- Test environment class: `software` / `scripted_fixture` / `gazebo` / `physical`
- Test window:
- Product and adapter versions:
- Out of scope:

## Real task

- User job:
- Starting state:
- Goal state:
- Semantic actions under test:
- Required adapters:
- Measurable success condition:
- Evidence required to confirm success:
- Failure and recovery cases:

## Responsibilities

| Area | Workbench owner | Partner owner |
|---|---|---|
| Environment preparation | | |
| Test data or fixtures | | |
| Operator time | | |
| Logs/evidence export | | |
| Issue triage | | |
| Safety and stop authority | Trusted runtime / site owner | Partner must follow site procedure |

## Exit criteria

- [ ] Evaluator and test window confirmed.
- [ ] Environment and version recorded.
- [ ] Task can be started from a known state.
- [ ] Normal and failure paths are defined.
- [ ] Evidence bundle and privacy handling are agreed.
- [ ] Continue, change, pause, or stop decision has an owner and date.

## Guardrails

- Do not promise a custom feature, delivery date, price, or physical success without owner approval.
- Do not place partner-identifying data or private logs in Git.
- Do not convert a partner's verbal approval into `confirmed` without the required observation evidence.
- Do not let a scenario manifest contain joint-level, CAN, controller, or emergency-stop fields.
