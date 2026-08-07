# workbench-1

A tabletop robot that verifies task completion instead of assuming it.

[English](README.md) · [简体中文](README.zh-CN.md)

---

## Problem

Tell a robot to put a block in a tray. It moves, reports success, and the block is on the floor.

The function returned OK, so the robot thinks it succeeded. But the task failed.

Most demos can't tell these apart. This one tries to.

---

## What it does

Single arm, table, simulation. The red-block task remains a frozen regression baseline; the v0.2 benchmark also covers three-part kitting, multi-workpiece inspection, obstacle-clearance recovery, and evidence-first parcel intake. You give it a bounded goal in plain text, it:

- Looks at every required entity in the scene
- Routes the goal to a bounded semantic plan (`observe`, `grasp`, `place`)
- Executes through MoveIt
- **Checks afterwards**: are all required goal conditions satisfied, with no extra kit parts?
- If unsure (camera lost track, low confidence, stale evidence), says "I can't confirm" instead of guessing
- Re-observes and retries recoverable failures while retaining the failed attempt in replay

The model picks a goal, but cannot send joint positions or velocities. That boundary is enforced by code, not prompts.

---

## Current state

**Works today:**
- Contract definitions (11 JSON schemas)
- Event store with replay
- Template planner for five task families (no model needed)
- Task-specific verification for placement, exact kit contents, inspection confidence, workspace clearance, and policy-derived parcel routing
- Read-only multi-entity dashboard with ordered replay, recovery history and evidence inspection
- Offline container, health endpoints, structured logs and release/SBOM workflow
- 12 frozen v0.1 baselines plus 24 expanded v0.2 scenarios with deterministic seed checks
- 50 golden task requests across five families plus 26 dangerous requests that must fail closed
- CI running lint, contracts, evaluation fixtures, offline demo and container smoke checks

**Not built yet:**
- Gazebo world
- MoveIt grasp/place
- Real camera (OpenCV + AprilTag)
- Open-ended natural language → plan (local model; bounded template routing works today)
- Gazebo-backed evaluation results (the committed runs are explicit scripted fixtures)

Each unbuilt piece has a frozen contract. You can build one without waiting for the others.

---

## Try it

Ubuntu 24.04 or WSL2, Python 3.12, no GPU required.

```bash
git clone https://github.com/Quchaosheng/workbench-desk-robot.git
cd workbench-desk-robot
make bootstrap
make demo-scripted
```

`demo-scripted` runs the full chain (observe → plan → verify → replay) in pure Python, no simulator. Fast feedback loop.

Other commands:

```bash
make test             # unit + contract tests
make lint             # ruff check
make check            # everything CI runs
```

Once Gazebo integration lands:

```bash
make sim              # start world + arm + camera
make demo             # full run, fixed script
```

Task dashboard, no network or GPU required:

```bash
make dashboard
# open http://127.0.0.1:8080
```

Container path:

```bash
docker compose up --build
curl http://127.0.0.1:8080/healthz
```

The dashboard API is read-only. Every HTTP write method returns `405`; this service contains no ROS, motion, MCU or emergency-stop publisher.

---

## Three things that matter

**1. Action result splits "sent" from "confirmed"**

Most code treats a successful write as a successful action. Here they're separate:

```python
ActionResult(
    dispatch_state="sent",       # frame left the host
    device_state="unconfirmed",  # device hasn't replied
    outcome="timeout"
)
```

**2. Verification is three-valued, not boolean**

```python
status = "confirmed"              # goal met, here's the evidence
status = "refuted"                # goal definitely not met  
status = "insufficient_evidence"  # can't tell, here's what's missing
```

A boolean forces the system to guess when it doesn't know. Three states let it say "I don't know."

**3. The model never controls motors**

It picks from six actions: `observe`, `grasp`, `place`, `ask_confirm`, `express`, `stop`. 

Joint angles, velocities, emergency stop are outside its reach. If it returns something off-list, the request fails closed.

---

## Extending it

The one-block demo is the regression floor, not the capability ceiling. The current scripted benchmark already exercises exact three-part kits, evidence-only inspection, and ordered obstacle-clearance recovery behind the same contracts.

**Add a task:** Write a new verifier. The system asks "is claim X true?" — it doesn't care if X is "block in tray" or "cable seated" or "6 screws present."

**Add a sensor:** Anything that outputs `observation.schema.json` is a sensor. Force sensor, depth camera, barcode reader — world model doesn't care which.

**Add an arm:** Motion consumes `semantic_action`, emits `action_result`. Swap Panda for UR5e or a real arm, nothing above changes.

**Add a planner:** Template planner and LLM planner already sit behind `ModelProvider`. Search-based or learned planner is a third implementation.

Rule: new capability arrives as a new implementation behind an existing contract. If you need to change a schema, talk first.

---

## Roadmap

v0.1 is deliberately small so verification can be proven correct before stacking on it. v0.2 broadens the offline evaluation surface without pretending scripted evidence is simulator or hardware evidence.

- **v0.1** — frozen one-arm, one-task regression baseline
- **v0.2** — five task families and richer failure handling (scripted pipeline implemented; Gazebo pending)
- **v0.3** — real hardware behind the same contracts
- **later** — mobile base (verifier generalizes to nav goals), multi-arm

Two things won't change:
- Model never controls joints/velocity/stop/completion
- Success claims carry evidence

---

## Metrics

Numbers v0.1 aims to hit. Ones marked **0** are release blockers.

| Safety | Target |
|---|---|
| False completion (reported done, wasn't) | **0** |
| Collisions / joint limit violations | **0** |
| Model emitting raw joint control | **0** |

| Task | Target |
|---|---|
| Grasp success (scripted, no faults) | ≥ 90% |
| Verified task completion rate | ≥ 80% |
| Recovery after first failure | ≥ 70% |
| Task time P95 | < 120s |
| Evaluated task families | ≥ 5 |
| Complex-task share | ≥ 50% |
| Goal-condition coverage | 100% |

| Evidence | Target |
|---|---|
| Same event log → same state | 100% |
| Verification carries evidence refs | 100% |
| Same seed → same scene config | 100% |

| System | Target |
|---|---|
| Clone → running demo, no model | < 90s |
| Clone → running demo, full stack | < 180s |
| GPU required | no |

---

## What this proves and doesn't prove

Simulation only. Being clear about the boundary is part of the point.

| Proven | Not proven |
|---|---|
| Software contracts, event integrity, replay | CAN electrical, bus timing |
| State machine transitions | Physical actuator dynamics |
| Verification logic, evidence chains | Sensor noise, lighting drift |
| Grasp success in Gazebo | Grasp success on real hardware |

Software safe-stop ≠ hardware emergency stop. Gazebo numbers don't transfer to real grippers without re-validation.

Scripted evaluation fixtures also do not prove Gazebo performance. They exercise event ordering, evidence coverage, replay and reporting, and are marked `release_eligible: false`. See [documented fixture failures](docs/evaluation/failure-cases.md) and the [container runbook](docs/deployment/container.md).

Parcel handling is intentionally limited to parcels already on the tabletop intake area. It scans the complete batch before manipulation, routes only verified intact parcels to the pickup shelf, and isolates condition exceptions before label-only exceptions. Capacity preflight rejects a batch before any manipulation if the pickup or quarantine destination cannot hold it. The current arm has no mobile base, elevator, or parcel-locker access; those requests fail closed instead of being simulated as completed.

---

## Contributing

Start with:

1. Read `AGENTS.md` (working rules, short)
2. Read the schema for the boundary you're touching (`interfaces/json_schema/`)
3. Open an issue describing the module and contract you'll satisfy
4. One module per PR

Full workflow in `CONTRIBUTING.md`, architecture in `docs/architecture/system.md`.

Six rules:
- `interfaces/` is the source of truth for module boundaries
- Planner emits semantic actions, never joint positions
- World model decides state meaning and task completion
- Scenarios/seeds/faults frozen before evaluation
- Success claims need events and reproducible evidence
- AI tools don't merge, release, change safety config, or decide completion

"Done" means: merged with CI green, a test that would catch the regression, a command someone else can run, and an evidence reference.

This project uses AI assistance. Contracts, invariants, and merge decisions are human-owned. If you contribute a module, you should be able to explain any file in it.

---

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).  
Third-party asset licenses in [THIRD_PARTY_REVIEW.md](THIRD_PARTY_REVIEW.md).
