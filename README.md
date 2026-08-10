# workbench-1

A tabletop robot that verifies task completion instead of assuming it.

[English](README.md) | [简体中文](README.zh-CN.md)

---

## Core Contributions (Kernel Engineering)

This project combines systems integration, runtime architecture, and task verification. The kernel engineering work includes:

**Event Store & Replay**
- Append-only event log with deterministic replay from any checkpoint
- Schema-versioned events validated against explicit contracts
- State reconstruction from event stream without external snapshot dependency

**Contract-Driven Architecture** 
- 11 JSON schemas defining all module boundaries (`interfaces/json_schema/`)
- Fail-closed validation: off-contract requests rejected at ingress, not execution
- Matching Pydantic models and contract checks guard producers and consumers against drift

**Evidence-First Verification**
- Three-valued logic (confirmed / refuted / insufficient_evidence) replaces boolean success
- Verification carries structured evidence references, not just pass/fail flags
- Same seed → same scene → same event sequence → deterministic evaluation

**System Reliability**
- Split-host controller/simulation with readiness probes and peer availability checks
- Structured logging, health endpoints, SBOM workflow, and hash-bound hardware evidence
- Reproducible startup P50/P95 metrics, CPU/RAM profiling, and container smoke tests

**Hardware-Facing Foundations**
- A Linux `wbcan` SocketCAN kernel module with build, checkpatch, and privileged fault-test paths
- A platform-separated RISC-V safety-MCU scaffold for host, QEMU, and CH32V307 HALs
- Fail-closed hardware release gates covering procurement, manufacturing, QA, compliance, and field validation

**What's NOT included:** Gazebo world, MoveIt grasp/place, real camera (OpenCV + AprilTag), and Gazebo-backed evaluation results are pending. Committed fixtures are scripted pipeline tests, not hardware evidence.

**Role Boundary:** Model routes to bounded semantic actions; joint control, velocities, and emergency stop remain in trusted code outside model reach.

---

## Problem

Tell a robot to put a block in a tray. It moves, reports success, and the block is on the floor.

The function returned OK, so the robot thinks it succeeded. But the task failed.

Most demos can't tell these apart. This one tries to.

---

## What it does

The current runnable path is a deterministic, scripted tabletop runtime. The red-block task remains a frozen regression baseline; the v0.2 benchmark also covers three-part kitting, multi-workpiece inspection, obstacle-clearance recovery, and evidence-first parcel intake. You give it a bounded goal in plain text, it:

- Looks at every required entity in the scene
- Routes the goal to a bounded semantic plan (`observe`, `grasp`, `place`)
- Executes semantic actions through the scripted runtime (MoveIt integration is pending)
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
- Task-specific verification for placement, exact kit contents, inspection confidence, workspace clearance, and manifest-reconciled parcel routing
- Read-only multi-entity dashboard with ordered replay, recovery history and evidence inspection
- Offline container, health endpoints, structured logs and release/SBOM workflow
- A localhost-only Ollama runner: the model routes to five bounded families, while trusted code emits semantic actions
- Reproducible startup, stage P50/P95, CPU/RAM and hash-bound hardware evidence tooling
- Split-host controller/simulation Compose topology with readiness failure when the peer is unavailable
- Linux `wbcan` SocketCAN kernel module sources and CI build/checkpatch coverage; runtime fault tests require a privileged Linux host
- RISC-V safety-MCU host/QEMU/board HAL scaffold with CI checks that preserve an explicit incomplete status
- Auditable hardware engineering packages and a fail-closed release report; the current report remains `RELEASE_BLOCKED` pending external evidence
- MkDocs operator manual covering installation, daily operation, maintenance, troubleshooting, and the 90-minute demo
- 12 frozen v0.1 baselines plus 24 expanded v0.2 scenarios with deterministic seed checks
- 50 golden task requests across five families plus 26 dangerous requests that must fail closed
- CI running lint, contracts, evaluation fixtures, offline demo and container smoke checks

**Not built yet:**
- Gazebo world
- MoveIt grasp/place
- Real camera (OpenCV + AprilTag)
- Gazebo-backed evaluation results (the committed runs are explicit scripted fixtures)
- Physical build, supplier quotes, laboratory certification, and field-validation evidence

Real camera, Gazebo and hardware evidence still require external equipment; repository fixtures are never promoted as hardware evidence.

---

## Try it

Ubuntu 24.04 or WSL2, Python 3.12, no GPU required.

```bash
git clone https://github.com/Quchaosheng/workbench-desk-robot.git
cd workbench-desk-robot
make bootstrap
make demo-scripted
make performance-test
```

`demo-scripted` runs the full chain (observe -> plan -> verify -> replay) in pure Python, with no simulator. It is the fastest feedback loop.

Other commands:

```bash
make test             # unit + contract tests
make lint             # ruff check
make check            # core Python checks and offline demos
make docs             # strict MkDocs build
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

Provision the optional local model once; runtime traffic stays on an internal Docker network:

```bash
docker compose --profile model-bootstrap run --rm model-bootstrap
docker compose --profile model up -d
docker compose run --rm dashboard python tools/scripts/local_runner.py \
  --provider ollama --endpoint http://model:11434 --allow-host model \
  --goal "Handle the parcels already in the intake area"
```

See [`docs/performance/README.md`](docs/performance/README.md) and
[`docs/deployment/multi-host.md`](docs/deployment/multi-host.md) for evidence and split-host deployment.
Operator and maintainer procedures start at [`docs/user-guide/index.md`](docs/user-guide/index.md).
Hardware release status is generated by:

```bash
python hardware/release/tools/check_release_readiness.py
```

A successful report validation means that repository evidence is internally consistent. It does not clear the external blockers or release physical hardware.

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

## Roadmap

v0.1 frozen regression → v0.2 five task families (scripted) → v0.3 hardware. Model boundary and evidence requirements won't change.

---

## Metrics

Key targets for v0.1. Safety metrics marked **0** are release blockers.

| Category | Metric | Target |
|---|---|---|
| **Safety** | False completion (reported done, wasn't) | **0** |
| | Collisions / joint limit violations | **0** |
| | Model emitting raw joint control | **0** |
| **Task** | Verified task completion rate | >= 80% |
| | Recovery after first failure | >= 70% |
| **Evidence** | Verification carries evidence refs | 100% |
| | Same seed -> same scene config | 100% |
| **System** | Clone -> running demo, no model | < 90s |
| | GPU required | no |

---

## What this proves and doesn't prove

Simulation only. Software contracts and Gazebo behavior don't prove CAN electrical, actuator dynamics, or sensor noise. Scripted fixtures exercise event logic, not Gazebo performance.

**Software safe-stop is not a hardware emergency stop.** Gazebo numbers don't transfer to real grippers without re-validation.

Scripted evaluation fixtures also do not prove Gazebo performance. They exercise event ordering, evidence coverage, replay and reporting, and are marked `release_eligible: false`. See [documented fixture failures](docs/evaluation/failure-cases.md) and the [container runbook](docs/deployment/container.md).

Parcel handling is intentionally limited to parcels already on the tabletop intake area. It scans the complete batch before manipulation, routes only verified intact parcels to the pickup shelf, and isolates condition exceptions before label-only exceptions. Capacity preflight rejects a batch before any manipulation if the pickup or quarantine destination cannot hold it. The current arm has no mobile base, elevator, or parcel-locker access; those requests fail closed instead of being simulated as completed.

---

## Contributing

Start with `AGENTS.md` (working rules) and the schema for your boundary (`interfaces/json_schema/`). Full workflow in `CONTRIBUTING.md`, architecture in `docs/architecture/system.md`.

Core rules: `interfaces/` defines module boundaries. Planner emits semantic actions, never joint positions. Success claims need events and reproducible evidence.

---

## License

Apache-2.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE).
Third-party asset licenses in [THIRD_PARTY_REVIEW.md](THIRD_PARTY_REVIEW.md).
