# Kernel (#13) - ROS 2 System Layer

## Overview

内核工程师的 P1 完整实现 (K1-K10)

## Components

- **K1-K2**: Schema Compiler (JSON Schema → TypeScript + Python)
- **K3**: Version Registry (schema version management)
- **K4-K5**: Communication Layer (versioned messages + schema validation)
- **K6-K7**: Event Store (append-only JSONL log with replay)
- **K8**: ROS 2 Lifecycle (created → configured → active → deactivated → finalized)
- **K9-K10**: System Startup (bootstrap + checklist)

## Usage

```python
from workbench.kernel.schema_compiler import SchemaCompiler
from workbench.kernel.event_store import EventStore
from workbench.kernel.lifecycle import LifecycleManager

# Schema compilation
compiler = SchemaCompiler(schemas_dir)
compiler.load_schemas()
compiler.compile_all(py_output_dir, ts_output_dir)

# Event logging
store = EventStore(log_file)
store.append(
    {
        "event_id": "event-1",
        "run_id": "run-1",
        "sequence_no": 0,
        "event_type": "observation",
        "occurred_at": "2026-08-13T00:00:00Z",
        "payload": {"entity_id": "red_block"},
    }
)
checkpoint = store.create_checkpoint()
replayed_events = store.replay(from_checkpoint=checkpoint)

# System lifecycle
manager = LifecycleManager()
node = manager.create_node("kernel")
manager.startup_sequence()
```

The default Event Store accepts one contiguous, contract-shaped run. Open legacy
object logs with `EventStore(path, legacy_objects=True)` only while migrating them.

## Tests

```bash
python tests/test_k1_k10.py
```

All K1-K10 tests passing.
