# task_utils

Shared standard-library utilities used across Workbench task boundaries.

Implemented today:

- `exclusive_file_lock`: persistent sidecar-file locking backed by `flock` on
  POSIX and one-byte `msvcrt` locking on Windows. It serializes both threads and
  processes and does not remove the lock file after use.

```python
from workbench_task_utils import exclusive_file_lock

with exclusive_file_lock("state.json.lock"):
    update_state()
```

Spatial containment, pose comparison, confidence aggregation, and evidence-ref
helpers remain planned and will be added only when repeated verifier patterns
need them.
