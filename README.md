# Workbench-1

**An evidence-first tabletop robot workbench: task completion must be verified, not assumed.**

[English](README.md) · [简体中文](README.zh-CN.md)

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![ROS 2](https://img.shields.io/badge/ROS_2-Jazzy-22314E?logo=ros&logoColor=white)](https://docs.ros.org/en/jazzy/)
[![Gazebo](https://img.shields.io/badge/Gazebo-Harmonic-FB7A00)](https://gazebosim.org/)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)

A single-arm tabletop robot in simulation. You type a goal in natural language; the
system observes, plans typed actions, executes, and then **checks whether the goal was
actually achieved**. When evidence is missing or contradictory it reports uncertainty
instead of claiming success.

```text
"Put the red block in the tray."

camera  ->  Observation      object, pose, confidence, evidence refs
        ->  WorldState       facts + beliefs, event-sourced
        ->  TaskGraph        constrained; the model cannot emit joint commands
        ->  grasp / place    MoveIt 2 + Virtual MCU safety layer
        ->  Verifier         "is the block inside the tray?" — with evidence
        ->  on failure       re-observe, retry, or ask for confirmation
        ->  express          idle / thinking / uncertain / pleased
        ->  Dashboard        replay the task, actions, errors and result
```

A demo run always includes one injected failure. A run that only shows the happy path is
not considered a passing demo.

---

## Why this exists

Most robot demos report success when the last command returns OK. That is not the same as
the task being done. This project treats the gap between *"the command was sent"* and
*"the goal was achieved"* as the actual engineering problem.

- **A returned ACK is not proof of execution.** The MCU layer separates "frame written"
  from "device confirmed" as distinct states.
- **A completed action is not proof of task success.** The Verifier independently checks
  world state against the goal, using evidence it can point to.
- **Insufficient evidence is a valid answer.** The system may report "cannot confirm" and
  re-observe rather than emit a plausible lie.
- **The language model never holds execution authority.** It selects from an allowlisted
  set of typed semantic actions. Joint values, velocities, stop and completion judgment
  are outside its reach by construction.

---

## Status

### Implemented

| Capability | Path |
|---|---|
| Typed Python contracts + committed JSON Schemas | `interfaces/`, `libs/contracts/` |
| Deterministic WorldState reducer (event-sourced) | `services/world_model/` |
| Tray-containment verifier with evidence refs | `services/world_model/` |
| SQLite event store + replay query | `services/backend/` |
| Constrained template TaskGraph planner | `services/agent_runtime/` |
| Virtual MCU safety state machine | `firmware/virtual_mcu/` |
| Scenario manifest schema + validator | `sim/scenarios/`, `tools/scripts/` |
| Contract tests + pure-Python end-to-end dry run | `tests/`, `tools/scripts/` |

### Not yet implemented

These are the integration surfaces. The foundation deliberately does not fake them —
each is a real module boundary with a frozen contract already defined.

| Capability | Contract it must satisfy |
|---|---|
| Gazebo world, assets, camera, lighting, spawn/reset | `scenario.schema.json` |
| MoveIt 2 grasp / place | `semantic_action.schema.json` → `action_result.schema.json` |
| Observation from real camera (OpenCV + AprilTag/colour) | `observation.schema.json` |
| Natural language → TaskGraph, local-model-first | `task_graph.schema.json` |
| Fault injection | `scenario.schema.json` |
| Dashboard + emotion expression | `world_event.schema.json`, `emotion_intent.schema.json` |

### Out of scope

- No mobile base, no second active arm
- No vision or LLM training — perception is classical CV on known targets
- No real mechanics, motors, power or PCB
- **The model never controls joints, velocity, stop, or completion judgment**
- No second simulator, second database, or second runtime agent

---

## Target metrics

These are the numbers the system is built to hit. Values marked **0** are
non-negotiable release gates.

### Safety and correctness

| Metric | Target |
|---|---|
| False completion — claimed done but not done | **0** |
| Collisions / joint-limit violations | **0** |
| Model emitting raw joint control (authority escape) | **0** |
| Dangerous-request interception at policy layer | 100% |
| Key event field completeness | 100% |

### Task performance

| Metric | Target |
|---|---|
| Scripted grasp-and-place success rate | ≥ 90% |
| Verified task completion rate (VTCR) | ≥ 80% |
| Post-failure recovery success rate | ≥ 70% |
| Task completion time, P95 | < 120 s |

### Agent and perception

| Metric | Target |
|---|---|
| Semantic tool-call legality rate | ≥ 95% |
| Local (offline) planning coverage | ≥ 50% |
| Known-target detection recall | ≥ 90% |
| Observation required-field completeness | 100% |

### World model and evidence

| Metric | Target |
|---|---|
| State hash consistency across identical event streams | 100% |
| WorldState consistency | ≥ 90% |
| Fixed-task replay success rate | ≥ 95% |
| Verification conclusions carrying evidence refs | 100% |

### Simulation and reproducibility

| Metric | Target |
|---|---|
| Frozen scenario schema validation | 100% |
| Scene config hash identity under same seed | 100% |
| Scene reset success rate, 10 consecutive | 100% |
| Fault injection trigger rate | ≥ 95% |

### System

| Metric | Target |
|---|---|
| One-command start to usable — no-model path | < 90 s |
| One-command start to usable — full stack with local model | < 180 s |
| CUDA hard dependency | none |
| External reproduction | ≥ 2 of 3 people start within 60 min |

---

## Quick start

Ubuntu 24.04 or WSL2, Python 3.12.

```bash
make bootstrap        # install dev dependencies
make test             # unit + contract tests
make contract         # validate JSON Schemas against examples
make scenario-check   # validate frozen scenario manifests
make demo-scripted    # pure-Python contract dry run, no physics
```

`make demo-scripted` is a **contract dry run, not a physics simulation**. It proves the
event / verification / replay chain end to end without ROS 2 or Gazebo, so you can work
on any module without a full simulation stack installed.

Simulation entry points, once the Gazebo layer lands:

```bash
make sim              # launch Gazebo world + arm + camera
make sim-reset SEED=… # reset scene from a seed
make demo             # scripted end-to-end, no model required
make demo-llm         # full stack with local model
```

---

## Interface contracts

Eleven schemas define every module boundary. They are frozen: changing one requires
approval and notification of all consumers, because another module is already written
against it.

| Schema | Producer | Consumers |
|---|---|---|
| `world_event` | all modules | Dashboard |
| `observation` | perception | world model |
| `action_result` | motion | world model |
| `semantic_action` | agent runtime | motion |
| `world_state` | world model | agent runtime, dashboard |
| `verification_result` | world model | agent runtime, dashboard |
| `task_graph` | agent runtime | motion |
| `mcu_protocol` | virtual MCU | motion |
| `emotion_intent` | dashboard | dashboard |
| `scenario` | scenario factory | world model, bringup |
| `pose` | shared | all |

Schemas live in `interfaces/json_schema/`, one valid example each in
`interfaces/examples/`. `make contract` validates every example against its schema.

Four questions are answered for every field before a schema is frozen:

1. When this field is missing, does the consumer reject, degrade, or default?
2. Who may write it? Multiple writers is a conflict source.
3. What is its time base — monotonic, wall clock, or none?
4. Can it be contaminated by evaluation ground truth? Oracle fields stay physically
   separate from runtime fields.

Three contract decisions worth knowing before you write code against them:

- **`action_result` separates `dispatch_state` from `device_state`.** A written frame
  cannot be read as a confirmed device action; that distinction is enforced by the type,
  not by convention.
- **`verification_result.status` is three-valued** — `confirmed` / `refuted` /
  `insufficient_evidence`. There is no boolean "done" field, because "I cannot confirm
  this" must be representable.
- **`mcu_protocol` splits the command id range.** Commands use ids ≤ 32767, stops use
  ≥ 32768, so a stop acknowledgement can never be matched to a command.

---

## Repository layout

```
apps/dashboard/            replay, state and expression display
firmware/virtual_mcu/      protocol codec, safety state machine
interfaces/
  json_schema/             11 frozen contracts
  examples/                one valid example per schema
libs/contracts/            typed Python models
robot/
  bringup/                 launch files, health checks
  description/             URDF, TF, joint limits
  control/                 controllers, safety limits
services/
  agent_runtime/           planner, tool registry, model provider
  backend/                 FastAPI + SQLite + replay API
  perception/              OpenCV / AprilTag observation
  world_model/             reducer, verifier, fault injection
sim/scenarios/             frozen manifests + seeds
tests/
  unit/                    per-module behaviour tests
  contract/                schema conformance tests
tools/scripts/             validators, dry run, task packet checks
docs/
  architecture/            system structure
  decisions/               ADRs
```

---

## Verification boundary

Simulation-only project. What the results do and do not support:

| Verified | Not verified |
|---|---|
| Software contracts, event integrity, replay | Real electrical CAN, bus arbitration timing |
| State machine and safety-state transitions | Physical actuator dynamics, motor load |
| Task verification logic and evidence chains | Sensor noise, lighting variation, calibration drift |
| Grasp/place success **in Gazebo physics** | Grasp success on real hardware |
| Fault injection and recovery paths | Hardware emergency stop, safety certification |

A software safe-stop is not a hardware emergency stop. A `vcan` ACK is an
application-level response, not a data-link-layer acknowledgement. Gazebo grasp success
does not transfer to a physical gripper without re-validation.

---

## Contributing

Read [`AGENTS.md`](AGENTS.md) before writing code and
[`docs/architecture/system.md`](docs/architecture/system.md) before changing an
interface. [`CONTRIBUTING.md`](CONTRIBUTING.md) has the full workflow.

Rules that cannot be bypassed:

1. `interfaces/` is the cross-module contract source of truth.
2. The agent runtime emits semantic actions only — never joint positions or velocities.
3. The world model is the only owner of state semantics and completion verification.
4. Scenario manifests, seeds and fault types are frozen before formal evaluation.
5. Any success, safety or metric claim must have events and deterministic evidence.
6. AI tools do not merge, release, change safety configuration, or decide physical
   completion.

One issue and one bounded module at a time. Read the relevant schema before changing a
producer or consumer. Add or update a test for every deterministic behaviour change.
Never claim completion without a command, a test result, and an evidence reference.

This project is built with AI-assisted development. Contracts, invariants, verification
strategy and all merge decisions are owned by humans. Anyone who contributes a module
should be able to explain any file in it: why it is written that way, what the
alternative was, and why it was rejected.

---

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
Third-party asset licences are tracked in [THIRD_PARTY_REVIEW.md](THIRD_PARTY_REVIEW.md).
