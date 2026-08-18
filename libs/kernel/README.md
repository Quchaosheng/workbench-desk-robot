# Kernel (#13) - ROS 2 System Layer

## Overview

内核工程师的 P1 完整实现 (K1-K10)

## Components

- **K1-K2**: Schema Compiler (JSON Schema → TypeScript + Python)
- **K3**: Version Registry (schema version management)
- **K4-K5**: Communication Layer (versioned messages + schema validation)
- **K6-K7**: Event Store (append-only SQLite log with replay and checkpoints)
- **K8**: ROS 2 Lifecycle (created → configured → active → deactivated → finalized)
- **K9-K10**: System Startup (bootstrap + checklist)

## Usage

```python
from workbench.kernel.schema_compiler import SchemaCompiler
from workbench.kernel.event_store import EventStore, migrate_jsonl
from workbench.kernel.lifecycle import LifecycleManager

# Schema compilation
compiler = SchemaCompiler(schemas_dir)
compiler.load_schemas()
compiler.compile_all(py_output_dir, ts_output_dir)

# Event logging
store = EventStore("runs/events.sqlite3")
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

# One-time migration from a strict JSONL log:
migrate_jsonl("runs/events.jsonl", "runs/events.sqlite3")

# Backup/restore verifies a SHA-256 manifest before replacement:
store.backup("runs/events.snapshot.sqlite3")
restored = EventStore.restore("runs/events.snapshot.sqlite3", "runs/events-restored.sqlite3")

# System lifecycle
manager = LifecycleManager()
node = manager.create_node("kernel")
manager.startup_sequence()
```

The SQLite backend is the recommended runtime store. It persists checkpoints and
keeps the complete event JSON so unknown extension fields survive migration.
`.jsonl` remains a compatibility backend; open legacy object logs with
`EventStore(path, legacy_objects=True)` only while migrating them. PostgreSQL is
intentionally not bundled: add the approved DB-API driver and adapter when a
deployment supplies a PostgreSQL DSN.

Snapshots use SQLite's online backup API plus a SHA-256 sidecar manifest. Close
the destination store before restore; checksum, schema version, database
integrity and event count are checked before atomic replacement. Keep one daily
snapshot for 30 days. The initial local target is RPO <= 24 hours and RTO <= 30
minutes; deployment owners must tighten those values from measured restore drills.

## Tests

```bash
python tests/test_k1_k10.py
```

All K1-K10 tests passing.
