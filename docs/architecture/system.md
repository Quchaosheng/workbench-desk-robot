# System architecture

```text
Simulation camera -> Perception Observation -> World Model -> Agent Runtime
                                                  ^                 |
                                                  |                 v
Dashboard <- Event Store / Replay <- ActionResult <- Motion / Virtual MCU
```

## Runtime units

1. `robot/`: ROS 2, Gazebo adapter, MoveIt and semantic action execution.
2. `services/perception/`: produces `Observation`; it never writes WorldState.
3. `services/world_model/`: reducer, verifier, event store and replay read model.
4. `services/agent_runtime/`: converts a user goal into a typed `TaskGraph`.
5. `firmware/virtual_mcu/`: protocol and safe-state simulator.
6. `apps/dashboard/`: read-only display of event and replay data.

## Critical flow

1. Perception emits an `Observation` with frame, confidence and source.
2. World Model records a `WorldEvent`, applies the deterministic reducer and exposes `WorldState`.
3. Agent Runtime emits a typed semantic action from a `TaskGraph`.
4. Motion returns `ActionResult` with evidence references.
5. World Model verifies the expected result. Only it emits `VerificationResult`.
6. Backend/replay displays facts and evidence; it does not derive a second WorldState.

## Safety boundary

Agent Runtime cannot issue joint positions, velocity commands, emergency-stop decisions or physical completion claims. Those belong to Motion, Virtual MCU and the World Model verifier respectively.
