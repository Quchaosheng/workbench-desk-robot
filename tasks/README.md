# tasks

Task definitions: one directory per task type. Each task has a goal description,
a verifier, and a set of scenarios.

```
tasks/
  pick_place/    put object A into container B (v0.1 demo task)
  kitting/       assemble a kit from a parts tray
  inspection/    check N attributes of an object (present, colour, orientation)
  assembly/      connect two parts in a defined configuration
```

Adding a task:
1. Write a verifier in `tasks/<name>/verifier.py` that takes a `WorldState` and
   returns `VerificationResult`
2. Add at least 3 frozen scenarios to `sim/scenarios/frozen/`
3. Add a task description to `interfaces/examples/`
4. Write unit tests for the verifier

The verifier is the only thing that changes per task. Everything else
(planning, execution, event store, replay) is reused.
