# task_utils

Shared utilities for task verifiers:

- Spatial containment check (bounding box, convex hull)
- Pose comparison with configurable tolerance
- Confidence aggregation across multiple observations
- Evidence ref builder

Import in verifiers:
```python
from workbench_task_utils import contains, pose_close, aggregate_confidence
```

Not implemented yet — will be populated as repeated patterns emerge across
task verifiers in v0.1 and v0.2.
