# Design Partner Handoff and Physical-Evidence Boundary

Status: proposed handoff policy for Issue #318. This document defines the
boundary between a product trial and an engineering or safety acceptance; it
does not grant a scenario, partner, model, dashboard, or adapter control over a
robot. It is a documentation contract, not a new public interface or a
replacement for the trusted runtime and physical safety procedures.

## 1. Decision vocabulary

Every handoff decision applies to one named claim, one scenario version, and
one evidence class. It must name an owner, a next action, and a review date.

| Decision | Meaning | Required follow-up |
|---|---|---|
| `continue` | The declared claim is supported by its current evidence gate and the next bounded step is safe to schedule. | Record the next environment, owner, and evidence artifact. |
| `change` | The user problem is useful, but the task, action, success condition, or evidence request is ambiguous or out of bounds. | Revise the handoff and re-run the applicable readiness checks. |
| `defer` | The scope is acceptable, but a dependency, owner approval, environment, or eligible evidence source is missing. | Keep the claim open and record the blocking input and date. |
| `reject` | The request would cross a safety, privacy, contract, or authority boundary, or the evidence rule cannot be made truthful. | Preserve the reason and offer a bounded semantic alternative where one exists. |

`continue` never means “the robot is safe” or “the task is physically
complete” by itself. A product decision can continue a software trial while a
physical or safety claim remains `insufficient_evidence`, `not_executed`, or
`blocked`.

## 2. Semantic action contract

The Scenario layer describes a user task. It does not describe how a
controller should move. Until a separately approved versioned contract adds
more actions, the current public semantic action set is:

`observe`, `grasp`, `place`, `ask_confirm`, `express`, and `stop`.

A scenario may refer to an action only when that action is registered and
version-compatible. It may provide:

- a scenario ID and version, a bounded goal, and an opaque `target_id`;
- a registered semantic action name and a closed set of typed policy selectors;
- required adapter capability names, evidence-policy and verifier references,
  and a bounded recovery-policy reference;
- an expected starting state and observable success condition.

These names describe the handoff vocabulary only. They are not an instruction
to add fields to the current public Schema; any new public action or manifest
field still requires the normal producer/consumer approval process.

The following are never Scenario fields or Design Partner inputs:

- joint positions, Cartesian poses, trajectories, velocities, accelerations,
  efforts, force/torque limits, controller goals, planner internals, or TF
  commands;
- CAN arbitration IDs, raw CAN frames, retry/sequence internals, device
  handles, pin/IRQ/DMA assignments, firmware commands, or vendor register
  values;
- E-stop, safe-enable, watchdog, brake, power, reset, or emergency-recovery
  writes;
- credentials, network endpoints with write authority, arbitrary executable
  parameters, or an unbounded JSON property bag.

An adapter capability is a name and a versioned ownership reference, not a
permission to expose its implementation parameters. The adapter resolves
that reference against owner-approved configuration and fails closed when the
target, version, capability, or policy is unknown. A Design Partner can
describe the job and the observable goal; it cannot negotiate a controller
goal or safety limit in the Scenario manifest.

### Illustrative allowed request

The following is pseudocode for a handoff, not a new public JSON Schema:

```yaml
scenario_id: partner-parcel-001
scenario_version: "1"
goal:
  entity: parcel-17
  observed_condition: placed_in_slot
actions:
  - type: observe
    target_id: parcel-17
  - type: grasp
    target_id: parcel-17
    policy: standard_grasp_v1
evidence_policy: parcel-placement-observation-v1
verifier: parcel-slot-verifier-v1
recovery_policy: bounded-observation-retry-v1
```

The policy names above resolve to controlled definitions. They do not permit
the caller to add a pose, force, speed, joint, CAN, or controller field.

## 3. Motion adapter result boundary

The Motion adapter consumes a validated semantic action plus an approved
context. It returns a typed `ActionResult` and separate health/fault evidence;
it does not write `WorldState` and does not decide whether the user's goal is
observed.

### ActionResult minimum interpretation

The existing result contract carries the following distinctions:

| Field/group | What it proves | What it does not prove |
|---|---|---|
| `action_id`, `run_id`, timestamps, and clock | Which request and time interval were handled. | That the physical scene has the desired state. |
| `outcome` | The adapter's bounded execution outcome, such as `completed`, `failed`, `timeout`, or `safe_stop`. | Task-level success or user value. |
| `dispatch_state` | Whether the request left the trusted host boundary. | That a controller executed it correctly. |
| `device_state` | The device acknowledgement state when the adapter has one. | That perception observed the intended result. |
| `error_code`, `error_reason`, retry count | A stable diagnostic and bounded retry history. | Permission to retry indefinitely or bypass safety. |
| `evidence_refs` | Where supporting raw or derived records can be found. | Validity of a record that the referenced verifier has not accepted. |

In particular, `ActionOutcome.COMPLETED` and `DeviceState.CONFIRMED` are
execution/acknowledgement facts. They are not an observed WorldState fact.
Product task acceptance requires the relevant observation, provenance,
freshness/conflict checks, and World Model verifier result in addition to the
ActionResult. A missing or contradictory observation stays
`insufficient_evidence`; it is never filled in from a successful action.

### Health and fault record

For a product handoff, the Motion adapter must expose (or reference) a
bounded, read-only health/fault record. This may be an existing owner-
controlled artifact; it does not require a new public schema. It contains:

- adapter/source identity, interface and configuration/commit hash;
- readiness and lifecycle state, queue depth/capacity, drop/deadline counts,
  and the monotonic timestamp/clock used for the observation;
- stable fault code, severity, latched/non-latched state, first/last observed
  time, affected capability, and whether a bounded recovery is permitted;
- raw-capture or evidence references, without raw controller handles or
  private partner data.

Health is not a safety permissive. A healthy adapter cannot clear an E-stop,
enable a drive, or turn an unverified ActionResult into a verified task.

## 4. Handoff checklist

The handoff owner copies this table into the private trial record and commits
only anonymized IDs and opaque evidence references to the repository.

| Owner | Inputs required before the trial | Outputs required after the trial | Cannot authorize |
|---|---|---|---|
| Product / Project Owner | Problem card, partner reference, user job, declared claim, success condition, test window, privacy/consent choice | `continue`/`change`/`defer`/`reject`, product feedback record, next owner/date | Motion parameters, E-stop reset, release or physical-safety claim |
| Motion Owner | Versioned semantic action, known target/capability, approved context and preflight result | ActionResult, adapter health/fault record, execution/evidence references, stop outcome | Raw scenario controller goals, independent safety clearance, observed task truth |
| MCU / Safety Owner | Firmware/config hashes, node/lifecycle status, watchdog and safety-chain readiness, approved reset procedure | ACK/fault/heartbeat evidence, safety inhibit state, reset/stop disposition | Product completion, automatic clearing of a latched E-stop, arbitrary Scenario fields |
| Runtime / Integration Owner | Runtime version, policy/verifier versions, queue/lifecycle limits, event/evidence sink and read-only exposure configuration | Correlated run/event IDs, cancellation/shutdown result, provenance and replay references | Hardware E-stop authority, raw device write access, verifier override |
| Site / Partner Operator | Environment access, trained operator, known starting state, safety briefing, equipment and calibration references | Operator record, observed task feedback, raw evidence handoff, incident/abort report | Changing the product contract or approving an unsafe reset |
| Evidence / QA Reviewer | Declared evidence class, acceptance rule, artifact schema and hash procedure | Independent evidence review, status classification, gap list and disposition | Promoting a lower evidence class to physical or release evidence |

Minimum handoff inputs are: an opaque partner ID, scenario/version, named
claim, environment class, owner matrix, starting state, success and failure
conditions, preflight/abort rule, privacy decision, and an evidence owner.
No trial starts while one of these is silently assumed.

## 5. Evidence ladder

Evidence classes are independent. A higher class requires its own eligible
artifact; passing a lower class is not a promotion token.

| Class | May support | Required minimum evidence | Explicit limitation |
|---|---|---|---|
| `software` | Contract, parser, policy, lifecycle, and deterministic unit behavior | Versioned source/config, deterministic test output, and reproducible command | No user trial, physics, actuator, wire, or safety claim |
| `scripted_fixture` | Product-flow and failure-routing behavior using a controlled fixture | Fixture/manifest hash, run ID, replay/verifier output, failure corpus, and privacy-safe record | `release_eligible: false` by default; not Gazebo or physical evidence |
| `gazebo` | Declared simulator task behavior and simulation observations | Simulator/world/plugin/config hashes, seed/clock, raw run bundle, verifier output, and explicit simulator status | Not physical CAN, actuator, E-stop, calibration, or site acceptance |
| `physical` | Only the specifically declared hardware/site claim | Serialized unit and revision, approved configuration hashes, calibrated instruments, trained operator/reviewer, safety preflight, raw capture hash, and repeatable procedure | Does not automatically prove a different task, device, site, or release claim |

The evidence ladder is per claim, not per conversation. A Design Partner's
verbal approval, interview, or video can be useful product feedback, but none
of them alone is execution or physical evidence and none proves physical task
completion. The handoff record must retain the weaker status whenever evidence
is missing, stale, conflicting, or from the wrong class:

- `confirmed`: the declared evidence rule for this claim passed;
- `failed`: the declared run or task outcome was not met;
- `refuted`: the declared product hypothesis or claim was contradicted;
- `insufficient_evidence`: the run cannot establish the claim;
- `not_executed`: the required run or environment did not happen;
- `blocked`: a prerequisite or owner gate prevents execution.

For `physical`, the site procedure must additionally identify the independent
E-stop/safe-enable authority, power and motion inhibit state, calibration
references, abort criteria, and raw capture location/hash before energization.
If any required item is unavailable, the physical result remains
`not_executed` or `blocked`.

## 6. Abort, stop, recovery, and confirmation authority

These controls are intentionally separate:

| Control | Authority | Normal behavior | Failure behavior |
|---|---|---|---|
| `safe_stop` | Trusted runtime requests it; Motion/MCU-Safety and the hardware chain execute the stop | Cancel further action dispatch and drive the bounded stop path; record correlation and result | Any timeout, rejected stop, or missing acknowledgement is a fault and keeps motion inhibited |
| `abort` | Trusted runtime / orchestrator owns the run decision; site operator may request it | End the run, prevent new semantic dispatch, preserve events and evidence, and request `safe_stop` when motion may be active | Never report completion; leave the run failed, stopped, or insufficiently evidenced |
| E-stop | Physical site operator and independent MCU-Safety/safety circuit | Remove/inhibit hazardous energy through the out-of-band chain | Software, DDS, dashboard, or Design Partner cannot override or silently reset it |
| Recovery | Runtime may select only a finite, policy-approved recovery; Motion/MCU/Safety owner controls reset and re-enable conditions | Require fresh provenance-valid evidence after each attempt | Latched safety faults and uncertain state require manual owner disposition; no automatic enable |
| Manual confirmation | Authorized human/site owner, recorded with identity reference and time | Confirms an operator decision or readiness observation within the approved procedure | A model response, partner preference, or screenshot cannot substitute for required safety evidence |

`safe_stop` is therefore a trusted request boundary, not a Scenario-owned
implementation. E-stop and safe-enable remain independent even when the
runtime mirrors their status. Recovery cannot turn a failed verification into
success without new evidence, and no manual confirmation can waive a required
Safety Owner gate.

## 7. Product acceptance versus Motion/Safety acceptance

Record these as separate rows in the handoff:

| Claim | Product acceptance asks | Engineering/safety acceptance asks |
|---|---|---|
| User value | Did the named evaluator perform the bounded job and understand the result? | Was the task run through the approved interface and recorded reproducibly? |
| Action behavior | Was the interaction understandable and the declared action outcome useful? | Did the adapter enforce policy, limits, correlation, timeout, and cleanup? |
| Observed goal | Is the declared goal measurable and supported by fresh evidence? | Did the canonical observation/verifier path establish or refute it? |
| Safety | Did the operator receive clear stop/abort instructions? | Did the independent safety chain, watchdog, E-stop, and reset procedure pass their own gate? |
| Release | Is the scoped product claim worth continuing? | Are all required owner approvals and eligible release artifacts present? |

The product side may choose `continue` for a scripted or simulated learning
loop while the engineering side records the physical claim as
`not_executed`. It may not publish the latter as a product success.

## 8. Rejected request example

The following request must be marked `reject` by the handoff owner and Safety
Owner:

> “Add `joint_angles`, `velocity`, `torque_limit`, `can_frame`, and
> `emergency_stop: false` to the partner's scenario manifest so the operator
> can tune the task directly from the dashboard.”

It asks a scenario and UI to become a controller and safety writer, bypasses
Motion/MCU/Safety ownership, and makes a dashboard setting look like an
E-stop decision. The bounded alternative is to name a registered semantic
action and opaque target, keep limits in owner-controlled configuration, show
validated read-only health/evidence, and request `safe_stop` through the
trusted runtime when appropriate. A Safety Owner must refuse the original
request even if it would make the demo easier to operate.

## 9. Copyable handoff record

```text
Handoff ID / scenario ID and version:
Partner reference (opaque) / organization type:
Named claim and evidence class:
Decision: continue | change | defer | reject
Decision owner / Motion owner / MCU-Safety owner / site owner:
Test window and known starting state:
Allowed semantic actions and adapter capabilities:
Forbidden fields/authority confirmed:
Product acceptance condition:
Motion acceptance inputs and outputs:
MCU/Safety preflight, stop, and reset inputs/outputs:
Runtime lifecycle, queue, cancellation, and provenance evidence:
Required evidence artifacts and hashes:
Privacy/consent/retention reference:
Abort conditions and immediate stop procedure:
Missing evidence or blockers:
Next action / owner / due date / review date:
Release eligible: false (change only with the applicable release gate)
```

Use [Design Partner Scenario Record](design-partner-scenario-template.md) for
the basic trial record and this document for the authority, evidence, and
handoff decisions. The generic record remains intentionally lightweight; this
policy supplies the stricter boundary required before a real task is scheduled.

## 10. Next step and decision record

After the handoff is completed, use the following sequence. Each row needs a
named owner and a dated record; an empty date is a blocker, not permission to
proceed.

| Step | Owner | Required action | Output/status |
|---|---|---|---|
| 1. Prepare | Product / Project Owner | Attach the problem card, opaque partner reference, named claim, scenario/version, and proposed environment. | Handoff record with privacy and consent decision. |
| 2. Review | Motion, MCU/Safety, Runtime/Integration, and site owners | Confirm semantic actions, adapter capability, preflight, stop/abort boundary, and failure matrix. | `continue`, `change`, `defer`, or `reject`; unresolved disagreement stays `defer`/`reject`. |
| 3. Schedule | Product Owner and site owner | Set the test window, known starting state, operator, equipment, calibration references, and raw-evidence destination. | Trial start approval for the declared evidence class. |
| 4. Run | Site operator with trusted runtime and relevant adapter owners | Execute only the approved task; stop or abort on any declared condition and preserve the run. | Run ID, ActionResult/health records, observations, and raw evidence references. |
| 5. Review evidence | Evidence/QA Reviewer plus domain owners | Check hashes, provenance, freshness, conflicts, safety records, and the class-specific acceptance rule. | Claim status; gaps remain `insufficient_evidence`, `not_executed`, or `blocked`. |
| 6. Decide next | Product / Project Owner | Record the product decision and the next owner/action/date without upgrading the evidence class. | Follow-up Issue/PR or an explicit stop/defer decision. |

The minimum next-step record is therefore: `owner`, `action`, `due date`,
`review date`, `evidence reference`, and `status`. A verbal “looks good” is
not a completed handoff.
