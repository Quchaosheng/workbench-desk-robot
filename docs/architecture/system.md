# System architecture

```text
Simulation camera -> Perception Observation -> World Model -> Agent Runtime
                                                  ^                 |
                                                  |                 v
Dashboard <- Read-only HTTP API <- Event Store <- ActionResult <- Motion / Virtual MCU
```

## Runtime units

1. `robot/`: ROS 2, Gazebo adapter, MoveIt and semantic action execution.
2. `services/perception/`: produces `Observation`; it never writes WorldState.
3. `services/world_model/`: reducer, verifier, event store and replay read model.
4. `services/agent_runtime/`: converts a user goal into a typed `TaskGraph`.
5. `firmware/virtual_mcu/`: protocol and safe-state simulator.
6. `services/backend/`: health/readiness plus a read-only projection of ordered event streams.
7. `apps/dashboard/`: task status, four expression states, evidence inspection and deterministic replay.

## Critical flow

1. Perception emits an `Observation` with frame, confidence and source.
2. World Model records a `WorldEvent`, applies the deterministic reducer and exposes `WorldState`.
3. Agent Runtime emits a typed semantic action from a `TaskGraph`.
4. Motion returns `ActionResult` with evidence references.
5. World Model verifies the expected result. Only it emits `VerificationResult`.
6. Backend/replay displays facts and evidence; it does not derive a second WorldState or accept control writes.

## Operational boundary

- `/healthz` reports process health; `/readyz` checks that the event source is readable.
- `/api/runs` and `/api/runs/{run_id}/events` expose ordered read models.
- Event JSONL files are cached by path, modification time and size; changed files invalidate automatically.
- Static responses use ETags, while versioned vendored assets use immutable caching.
- `POST`, `PUT`, `PATCH` and `DELETE` return `405 read_only`.
- Service logs are JSON Lines with `service`, `source`, `run_id` and per-run `sequence_no` fields. The same record shape accepts `simulation` and `hardware` sources without changing analysis code.
- `apps/dashboard/data/` is fixture data for offline UI and API tests. It is never eligible as physical release evidence.

## Safety boundary

Agent Runtime cannot issue joint positions, velocity commands, emergency-stop decisions or physical completion claims. Those belong to Motion, Virtual MCU and the World Model verifier respectively.
