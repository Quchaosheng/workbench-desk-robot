# Frozen P1 scenarios

This directory contains the 12 immutable v0.1 evaluation manifests:

- normal: 3;
- occlusion / low confidence: 3;
- moving target: 3;
- grasp failure: 3.

Each manifest must contain a stable scenario ID, seed, world version, timeout and fault type. The expected outcome is held separately from generators and candidate-model prompts.

The same 12 manifests run against every system version under comparison. `python tools/scripts/validate_scenarios.py` also materializes every seed twice and rejects distribution drift or non-determinism.

The `expanded/` directory adds 18 P2 manifests for path blocking, low light, and multiple same-colour objects. It does not modify this frozen baseline.
