# Frozen scenarios

The Perception Owner expands this directory to 12 manifests before formal evaluation:

- normal: 3;
- occlusion / low confidence: 3;
- target moved: 3;
- grasp failed: 3.

Each manifest must contain a stable scenario ID, seed, world version, timeout and fault type. The expected outcome is held separately from generators and candidate-model prompts.

The same 12 manifests run against every system version under comparison, so a difference in results cannot come from a difference in scenarios.

Two fault classes are deliberately outside this matrix. Path blocking needs dynamic obstacles in the world and is out of scope. Service and MCU timeouts are covered by the Virtual MCU module's own fault tests, where the timeout, disconnect and stop paths can be asserted directly instead of inferred from a task outcome.
