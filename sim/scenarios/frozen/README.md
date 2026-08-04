# Frozen scenarios

The Simulation Owner expands this directory to 30 manifests before formal evaluation:

- normal: 6;
- occlusion / low confidence: 6;
- target moved: 6;
- path blocked: 6;
- grasp failed: 3;
- service or MCU timeout: 3.

Each manifest must contain a stable scenario ID, seed, world version, timeout and fault type. The expected outcome is held separately from generators and candidate-model prompts.
