# Workbench-1

**An evidence-first tabletop robot workbench: task completion must be verified, not assumed.**

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

The demo always includes one injected failure. A run that only shows the happy path is
not a passing demo.

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

## v0.1 scope

### Foundation — implemented

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

### Integration targets — owned per module, deliberately not faked

| Capability | Owner | Week |
|---|---|---|
| Gazebo world, assets, camera, lighting, spawn/reset | Linux | W1 |
| MoveIt 2 grasp / place emitting ActionResult | Motion | W2 |
| Observation from real Gazebo camera (OpenCV + AprilTag/colour) | Agent C | W2 |
| Natural language → TaskGraph, local-model-first | Agent A | W3 |
| Fault injection, 4 classes | World Model | W3 |
| Dashboard + emotion expression | Agent B | W3 |
| 12 frozen scenarios × 3 versions = 36 evaluation runs | Agent C | W4 |

### Out of scope for v0.1

- No mobile base, no second active arm
- No vision or LLM training — perception is classical CV on known targets
- No real mechanics, motors, power or PCB
- No path-blocking scenario class (requires dynamic obstacles)
- **The model never controls joints, velocity, stop, or completion judgment**
- No second simulator, second database, or second runtime agent

---

## Performance targets

Every number is a release gate, not an aspiration. Values marked **0** are non-negotiable.

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
| Full-system verified task completion rate (VTCR) | ≥ 80% |
| Post-failure recovery success rate | ≥ 70% |
| Task completion time, P95 | < 120 s |

### Agent and perception

| Metric | Target |
|---|---|
| Semantic tool-call legality rate | ≥ 95% |
| Local (offline) planning coverage | ≥ 50% — stretch 70% |
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
| Frozen scenario schema validation, 12 scenarios | 100% |
| Scene config hash identity under same seed | 100% |
| Scene reset success rate, 10 consecutive | 100% |
| Fault injection trigger rate, 4 classes | ≥ 95% |

### System and release

| Metric | Target |
|---|---|
| One-command start to usable — no-model path | < 90 s |
| One-command start to usable — full stack with local model | < 180 s |
| CUDA hard dependency | none |
| External reproduction | ≥ 2 of 3 people start within 60 min |
| Four-state comprehension rate, user study n=5 | ≥ 80% |
| Behaviour tests per module — lint counted separately | ≥ 15 |

---

## Evaluation design

Three system versions run the **same 12 frozen scenarios** with identical seeds.

| Version | Definition |
|---|---|
| A | Fixed script + plain state machine |
| B | Agent, with WorldState verification and re-observation **disabled** |
| C | Full system: Agent + WorldState + verification + recovery + expression |

Scenario mix: 3 normal · 3 occlusion/low-confidence · 3 target-moved · 3 grasp-failure.
**12 scenarios × 3 versions = 36 runs.**

Each run reports success rate, recovery rate, false completion, safety violations, human
intervention, task time, P50/P95, and failure samples.

Anti-gaming rules, enforced in code and review:

- The scenario factory **cannot read holdout expected answers**
- Oracle fields (`oracle_id`, ground-truth labels) enter the evaluation module only —
  never reconstruction, planning, or verification
- Sensor scores are never computed from oracle data
- Success rates may **not** be raised by relaxing safety limits, disabling collisions,
  widening joint limits, or leaking oracle data

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
event / verification / replay chain end to end without ROS 2 or Gazebo. The Linux, Motion
and Agent C owners replace its adapters with real ROS 2 / Gazebo while keeping the
contracts unchanged.

Full simulation entry points land in W1:

```bash
make sim              # launch Gazebo world + arm + camera
make sim-reset SEED=… # reset scene from a seed
make demo             # scripted end-to-end, no model required
make demo-llm         # full stack with local model
```

---

## Interface contracts

Ten schemas define every module boundary. They are frozen before parallel development
begins; changing one requires the owner's approval plus notification of all consumers.

| Schema | Owner | Producer | Consumers |
|---|---|---|---|
| `world_event` | World Model | all | Dashboard |
| `observation` | Agent C | Agent C | World Model |
| `action_result` | Motion | Motion | World Model |
| `semantic_action` | Agent A | Agent A | Motion |
| `world_state` | World Model | World Model | Agent A, Agent B |
| `verification_result` | World Model | World Model | Agent A, Agent B |
| `task_graph` | Agent A | Agent A | Motion |
| `mcu_protocol` | MCU | MCU | Motion |
| `emotion_intent` | Agent B | Agent B | Agent B |
| `scenario` | Agent C | Agent C | World Model, Linux |

Schemas live in `interfaces/json_schema/`, one valid example each in
`interfaces/examples/`. `make contract` validates every example against its schema.

Four questions are answered for every field before a schema is frozen:

1. When this field is missing, does the consumer reject, degrade, or default?
2. Who may write it? Multiple writers is a conflict source.
3. What is its time base — monotonic, wall clock, or none?
4. Can it be contaminated by oracle data? Evaluation fields stay physically separate
   from runtime fields.

---

## Module ownership

One owner per module. No shared ownership.

| Path | Owner | Scope |
|---|---|---|
| `services/agent_runtime/` | Agent A | TaskGraph, provider routing, typed tools |
| `apps/dashboard/` | Agent B | Interaction, emotion, replay display |
| `services/perception/` | Agent C | Observation producer, evaluation |
| `sim/scenarios/` | Agent C | Scenario manifests, seeds, validators, batch runs |
| `services/world_model/` | World Model | Reducer, verifier, event store, fault injection |
| `services/backend/` | World Model | FastAPI, SQLite, replay API |
| `robot/bringup/` | Linux | Launch files, health checks, world assets |
| `.github/`, `.devcontainer/`, `tools/` | Linux | Build, CI, dev environment, integration |
| `firmware/virtual_mcu/` | MCU | Protocol codec, watchdog, safe state |
| `robot/description/`, `robot/control/` | Motion | URDF, TF, controllers, motion safety |
| `docs/product/` | Product Owner | Scope, acceptance, release decisions |

`services/world_model/` owns state meaning and verification; it does not own UI or robot
control. `services/agent_runtime/` owns planning and typed tools; it does not write
WorldState facts.

---

## Rules that cannot be bypassed

1. `interfaces/` is the cross-module contract source of truth.
2. Agent Runtime emits semantic actions only — never joint positions or velocities.
3. World Model is the only owner of state semantics and completion verification.
4. Scenario manifests, seeds and fault types are frozen before formal evaluation.
5. Any success, safety or metric claim must have events and deterministic evidence.
6. AI tools do not merge, release, change safety configuration, or decide physical
   completion.

Read `AGENTS.md` before writing code, and `docs/architecture/system.md` before changing
an interface.

---

## Repository layout

```
apps/dashboard/            Agent B   replay, state, emotion display
firmware/virtual_mcu/      MCU       protocol codec, safety state machine
interfaces/
  json_schema/             10 frozen contracts
  examples/                one valid example per schema
libs/contracts/            typed Python models
robot/
  bringup/                 Linux     launch files, health checks
  description/             Motion    URDF, TF, joint limits
  control/                 Motion    controllers, safety limits
services/
  agent_runtime/           Agent A   planner, tool registry, provider
  backend/                 WM        FastAPI + SQLite + replay API
  perception/              Agent C   OpenCV/AprilTag observation
  world_model/             WM        reducer, verifier, fault injection
sim/scenarios/             Agent C   12 frozen manifests + seeds
tests/
  unit/                    per-module behaviour tests
  contract/                schema conformance tests
tools/scripts/             validators, dry run, task packet checks
docs/
  architecture/            system structure
  decisions/               ADRs
  product/                 execution plan, PM dashboard
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

## Development

Built with AI-assisted development. Interface contracts, invariants, verification
strategy and all merge decisions are owned by the module owners listed above. Every owner
can walk through any file in their module and explain why it is written that way, what
the alternative was, and why it was rejected.

Rules in `AGENTS.md` and `CONTRIBUTING.md` apply to human and AI contributions equally:
one issue and one bounded module at a time; read the schema before changing a producer or
consumer; add or update a test for every deterministic behaviour change; never claim
completion without a command, a test result, and an evidence reference.

---

## Release gates

`v0.1.0` is not released if any of these fail:

- False completion is not 0
- Any collision, joint-limit violation, or agent authority escape
- The scripted demo requires a cloud API to run
- Scenarios, seeds, or fault-injection rules are not versioned
- Key events are incomplete, or a task cannot be replayed
- The 36 evaluation runs have no raw data
- README does not state limitations and failure cases
- An external person cannot start the system by following the docs
- Any module owner cannot explain a spot-checked file in their module

---

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
Third-party asset licences are tracked in [THIRD_PARTY_REVIEW.md](THIRD_PARTY_REVIEW.md).
