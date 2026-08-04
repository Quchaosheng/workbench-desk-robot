# Workbench-1

**A robot arm that checks its own work — and says "I'm not sure" instead of guessing.**

[English](README.md) · [简体中文](README.zh-CN.md)

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![ROS 2](https://img.shields.io/badge/ROS_2-Jazzy-22314E?logo=ros&logoColor=white)](https://docs.ros.org/en/jazzy/)
[![Gazebo](https://img.shields.io/badge/Gazebo-Harmonic-FB7A00)](https://gazebosim.org/)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

---

## The problem

You tell a robot: *put the block in the tray.*

It moves. It reports **success**. The block is on the floor.

The command executed correctly. The task failed. Most robot demos cannot tell those
two things apart — they report success when the last function call returned OK.

This project can tell them apart. And when it genuinely doesn't know — the camera
lost sight of the block, the gripper never confirmed — it says **"I can't confirm
this"** and looks again, instead of reporting a success that didn't happen.

---

## What it does

A single arm on a table, in simulation. You type a goal in plain language:

```
> Put the red block in the tray.
```

Then the system:

1. **Looks** — finds the block and the tray with a camera, records how confident it is
2. **Plans** — turns your sentence into a short list of allowed actions
3. **Acts** — grasps and places, through a safety layer that can stop it
4. **Checks** — asks a separate question afterwards: *is the block actually in the tray?*
5. **Recovers** — if the answer is no or unclear, it looks again, retries, or asks you
6. **Shows its work** — every step, every error, replayable after the fact

A demo run always breaks something on purpose. If it only shows the happy path, it
doesn't count as passing.

<!-- TODO: demo GIF goes here once the Gazebo layer lands -->

---

## Why you might care

| If you are… | What's here for you |
|---|---|
| Building a robot that has to be trusted | A worked example of separating "command sent" from "task done", with the plumbing to prove it |
| Putting an LLM near hardware | A model that can pick a goal but structurally cannot emit a joint command |
| Learning ROS 2 / Gazebo / MoveIt | A small, complete stack you can run on a laptop with no GPU |
| Researching robot evaluation | 12 frozen scenarios, 3 system variants, and rules that stop you fooling yourself |

---

## Three ideas that shape the code

These are the load-bearing decisions. If you read nothing else, read these.

**1. "The message was sent" and "the device did it" are different states.**

Most code treats a successful write as a successful action. Here they're separate
fields on the result, so you cannot accidentally read one as the other:

```python
ActionResult(
    dispatch_state="sent",         # the frame left the host
    device_state="unconfirmed",    # the device has not confirmed yet
    outcome="timeout",
)
```

**2. "I don't know" is a real answer, not a failure.**

Verification returns one of three things, never a boolean:

```python
status = "confirmed"              # goal achieved, here is the evidence
status = "refuted"                # goal definitely not achieved
status = "insufficient_evidence"  # cannot tell — and here is what's missing
```

A boolean `done` field would force the system to guess. It has nowhere to put
uncertainty, so uncertainty becomes a lie.

**3. The language model never gets to move a motor.**

It picks from six allowed actions — `observe`, `grasp`, `place`, `ask_confirm`,
`express`, `stop`. Joint angles, velocities, emergency stop and "is the task done"
are outside its reach by construction, not by prompt instruction. If the model
returns something off-list, the request fails closed and no command is created.

---

## Try it

Ubuntu 24.04 or WSL2, Python 3.12. No GPU needed.

```bash
git clone https://github.com/Quchaosheng/workbench-desk-robot.git
cd workbench-desk-robot
make bootstrap
make demo-scripted
```

`make demo-scripted` runs the whole observe → plan → act → verify → replay chain in
pure Python, with no ROS 2 and no Gazebo. It's fast, and it means you can work on any
module without installing a simulator.

Other useful targets:

```bash
make test             # unit + contract tests
make contract         # check every schema against its example
make scenario-check   # check the frozen evaluation scenarios
```

Once the Gazebo layer lands:

```bash
make sim              # world + arm + camera
make sim-reset SEED=7 # rebuild the exact same scene from a seed
make demo             # full run, no model required
make demo-llm         # full run with a local model
```

---

## Where it is now

### Working today

| | |
|---|---|
| Typed contracts + JSON Schemas for every module boundary | `interfaces/`, `libs/contracts/` |
| World state built from an event log, reproducible by replay | `services/world_model/` |
| Verifier that answers "is it in the tray" with evidence | `services/world_model/` |
| Event store + replay API | `services/backend/` |
| Template planner (no model needed) | `services/agent_runtime/` |
| Virtual MCU with a real safety state machine | `firmware/virtual_mcu/` |
| Scenario definitions + validator | `sim/scenarios/` |
| Contract tests + end-to-end dry run | `tests/`, `tools/scripts/` |

### Not built yet

Each of these is a real module with a **frozen contract already written**. That's the
point: you can build one without waiting for the others, and it will fit.

| To build | Contract it has to satisfy | Good entry point if you know… |
|---|---|---|
| Gazebo world, camera, lighting, reset | `scenario.schema.json` | Gazebo / SDF |
| Grasp + place with MoveIt 2 | `semantic_action` → `action_result` | MoveIt, motion planning |
| Real camera detection (AprilTag / colour) | `observation.schema.json` | OpenCV |
| Natural language → plan, local model first | `task_graph.schema.json` | LLM tooling |
| Fault injection | `scenario.schema.json` | Python, test design |
| Dashboard + expression | `world_event`, `emotion_intent` | Web frontend |

---

## Extending it

The demo task is one block and one tray, but nothing in the architecture is tied to
that. Here's where you plug in.

**Add a new task.** A task is a goal string plus a verifiable claim. The Verifier asks
"is claim X true, and what's the evidence?" — it doesn't care whether X is
`block inside tray` or `door closed` or `six screws present`.

```python
# services/world_model/ — register a new claim type
"cable_seated_in_port" -> checks pose containment + a confirmation observation
```

**Add a new sensor.** Anything that can emit `observation.schema.json` is a sensor.
Force sensor, depth camera, barcode reader — the world model doesn't know or care
which, as long as each observation carries its own confidence and evidence refs.

**Add a new arm.** Motion consumes `semantic_action` and emits `action_result`.
Swapping Panda for UR5e or a real arm means writing a new adapter behind that pair of
contracts; nothing above it changes.

**Add a new planner.** The template planner and an LLM planner already sit behind the
same `ModelProvider` interface. A search-based or learned planner is a third
implementation, and the six-action allowlist still bounds what it can ask for.

**Add a new evaluation axis.** Scenarios are declarative manifests with a seed. New
fault class, new lighting condition, new object set — add manifests, don't touch code.

The rule that holds all of this together: **new capability arrives as a new
implementation behind an existing contract.** If you find yourself needing to change a
schema, that's a design conversation first, not a PR.

---

## Roadmap

v0.1 is deliberately small so that the verification layer can be proven correct before
anything is stacked on it.

| | Scope | Status |
|---|---|---|
| **v0.1** | One arm, one task, simulation. Verification, recovery and replay proven end to end | in progress |
| **v0.2** | Multiple task types; multi-step tasks; richer failure taxonomy | planned |
| **v0.3** | Real hardware bring-up behind the same contracts; hardware safety loop | planned |
| **v0.4** | Mobile base — the Verifier contract already generalises to navigation goals | idea |
| **later** | Multi-arm coordination; task learning from replayed failures | idea |

Two things are **permanent invariants**, not roadmap items. They will not be relaxed
in any version:

- The model never controls joints, velocity, stop, or completion judgment
- A claim of success always carries evidence, or it is not a claim of success

---

## Target metrics

The numbers v0.1 is built to hit. The ones marked **0** are release blockers — the
build does not ship if they are non-zero.

| Safety | Target |
|---|---|
| False completion — reported done, wasn't done | **0** |
| Collisions / joint-limit violations | **0** |
| Model emitting raw joint control | **0** |
| Dangerous request reaching the device layer | **0** |

| Task | Target |
|---|---|
| Grasp-and-place success (scripted) | ≥ 90% |
| Verified task completion rate | ≥ 80% |
| Recovery after a failure | ≥ 70% |
| Task time, P95 | < 120 s |

| Evidence and reproducibility | Target |
|---|---|
| Same event log replays to the same state | 100% |
| Verification conclusions carrying evidence | 100% |
| Same seed rebuilds the same scene | 100% |
| Fixed-task replay | ≥ 95% |

| Getting started | Target |
|---|---|
| Clone to running demo, no model | < 90 s |
| Clone to running demo, full stack | < 180 s |
| GPU required | no |
| Someone else can run it from the docs | 2 of 3 people, under an hour |

---

## What this does and doesn't prove

Simulation only. Being explicit about the boundary is part of the point of the project.

| Proven here | Not proven here |
|---|---|
| Software contracts, event integrity, replay | Real CAN electrical layer, bus timing |
| Safety state machine transitions | Physical actuator dynamics, motor load |
| Verification logic and evidence chains | Sensor noise, lighting drift, calibration |
| Grasp success **in Gazebo physics** | Grasp success on a real gripper |
| Fault injection and recovery paths | Hardware emergency stop, safety certification |

A software safe-stop is not a hardware emergency stop. A `vcan` ACK is an
application-level reply, not a data-link acknowledgement. None of the grasp numbers
transfer to real hardware without re-validation.

---

## Contributing

Contributions are welcome, including to the six unbuilt modules above.

Start here:

1. Read [`AGENTS.md`](AGENTS.md) — the working rules, short
2. Read the schema for the boundary you're touching, in `interfaces/json_schema/`
3. Open an issue describing the module and the contract you'll satisfy
4. One module per PR

[`CONTRIBUTING.md`](CONTRIBUTING.md) has the full workflow.
[`docs/architecture/system.md`](docs/architecture/system.md) explains how the pieces fit.

**Six rules that don't bend:**

1. `interfaces/` is the source of truth for anything crossing a module boundary
2. The planner emits semantic actions — never joint positions or velocities
3. The world model alone decides what state means and whether a task completed
4. Scenarios, seeds and fault types are frozen before an evaluation run
5. Any success or safety claim needs events and reproducible evidence behind it
6. AI tools don't merge, release, change safety config, or decide task completion

**What "done" means here:** merged with CI green, a behaviour test that would catch the
regression, a command someone else can run to reproduce it, and an evidence reference.
"It works on my machine" and "the AI wrote it and I haven't read it" are not done.

This project is built with AI assistance. Contracts, invariants and every merge
decision are human-owned. If you contribute a module, you should be able to explain any
file in it: why it's written that way, what else you considered, why you rejected it.

---

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
Third-party asset licences are tracked in [THIRD_PARTY_REVIEW.md](THIRD_PARTY_REVIEW.md).
