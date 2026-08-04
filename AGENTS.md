# Workbench-1 repository rules

## Always true

- Work on one Issue and one bounded module at a time.
- Read the relevant JSON Schema and examples before changing a producer or consumer.
- Add or update a test for every deterministic behavior change.
- Keep `robot/control/` and `firmware/` out of AI write tasks unless the human Owner explicitly approves them.
- Never claim a task is complete without a command, test result and evidence reference.

## Ownership boundaries

- `interfaces/` changes require the Runtime Owner, the World Model Owner and the affected producer/consumer Owner.
- `sim/` changes require Simulation; robot kinematics/control changes require Motion.
- `services/world_model/` owns state meaning and verification; it does not own UI or robot control.
- `services/agent_runtime/` owns planning and typed tools; it does not write WorldState facts.
- Linux owns build, launch, CI and integration configuration.

## AI task rule

AI write work requires a Task Packet with allowed paths, tests, evidence and stop conditions. Use `docs/task_packets/example-001-world-reducer.json` as the machine-readable example.

## Required checks

```bash
make test
make contract
make scenario-check
make context-check
```
