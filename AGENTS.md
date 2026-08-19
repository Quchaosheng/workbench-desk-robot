# Workbench-1 repository rules

## Always true

- Work on one Issue and one bounded module at a time.
- Read the relevant JSON Schema and examples before changing a producer or consumer.
- Add or update a test for every deterministic behavior change.
- Keep `robot/control/` and `firmware/` out of AI write tasks unless the human Owner explicitly approves them.
- Never claim a task is complete without a command, test result and evidence reference.

## Review boundaries

- `interfaces/` changes require three independent human approvals. The affected producer and every consumer must be notified before merge.
- A PR that changes a schema in `interfaces/` MUST update the matching Pydantic model in `libs/contracts/` in the same PR, with `make contract` passing. Splitting them across two PRs is how the schema and the model drifted apart before.
- `sim/` changes require simulation validation; robot kinematics/control changes require motion validation.
- `services/world_model/` defines state meaning and verification; it does not define UI or robot control.
- `services/agent_runtime/` defines planning and typed tools; it does not write WorldState facts.
- Build, launch, CI and integration configuration changes require integration review.

## AI task rule

AI write work requires a Task Packet with allowed paths, tests, evidence and stop conditions. Use `docs/task_packets/example-001-world-reducer.json` as the machine-readable example.

## Required checks

```bash
make test
make contract
make scenario-check
make context-check
```
