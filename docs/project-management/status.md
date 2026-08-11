# Status dashboard

Snapshot: 2026-08-11. Refresh this page weekly and whenever a release-blocking risk triggers.

## Status rules

| State | Meaning |
|---|---|
| GREEN | acceptance evidence exists and its validator passes |
| AMBER | work or evidence is incomplete, but a bounded recovery path exists |
| RED | a release blocker is active or required external evidence is absent |
| UNKNOWN | the metric has not been measured by an eligible source |

## Workstream status

| Workstream | State | Evidence | Next action |
|---|---|---|---|
| Deterministic foundation | GREEN | CI run `31405819237` passed on `main` | keep required checks green on every PR |
| Scripted regression | GREEN | nightly run `31423360868`; outputs are explicitly non-release | retain as contract/regression evidence only |
| Release automation | AMBER | tag run `31406815969` failed during SBOM release-asset upload; fix tracked in PR #21 | review, merge, then verify on the next human-owned release |
| Formal Gazebo evaluation | RED | `docs/evaluation/failure-cases.md` says 36 real Gazebo runs and independent audit are still required | integrate, execute, and retain raw external-runner logs |
| External cold start | RED | three participant records are required by `docs/context/EVIDENCE_INDEX.md` | recruit three unique participants and retain failures |
| Hardware release | RED | `hardware/release/generated/release_readiness_report.json` reports 12 blockers and `RELEASE_BLOCKED` | close each external/commercial/physical gate with referenced evidence |
| Procurement | RED | `hardware/procurement/generated/procurement_report.json` reports `ORDER_RELEASE_BLOCKED` | obtain dated quotes, AVL approval, and incoming inspection evidence |
| Dashboard / read-only UI | GREEN | backend behavior tests and committed fixture replay pass in CI | run documented usability study before a production usability claim |
| Security program | AMBER | secret scanning and push protection are enabled; continuous code/dependency review is not yet a required check | deliver the security baseline and decide required-check policy |

## Release metrics

| Metric | Target | Eligible current result | State |
|---|---:|---:|---|
| false completion | 0 | UNKNOWN - no formal Gazebo audit | UNKNOWN |
| collision or limit violation | 0 | UNKNOWN - no formal Gazebo audit | UNKNOWN |
| fixed-script grasp success | >=90% | UNKNOWN - scripted fixtures are not physics runs | UNKNOWN |
| verified task completion rate | >=80% | UNKNOWN - formal 36-run set absent | UNKNOWN |
| external cold-start success | >=2 of 3 | 0 eligible participant records | RED |
| hardware release blockers | 0 | 12 | RED |
| foundation CI | pass | passed run `31405819237` | GREEN |

## Next seven days

| Priority | Action | Owner | Evidence expected |
|---|---|---|---|
| P1 | merge and verify the least-privilege SBOM fix | Integration + human reviewer | green PR CI and next release workflow result |
| P1 | freeze the formal Gazebo run command and output layout | Simulation + Integration | external-runner command, raw log sample, hash/index |
| P1 | approve the security audit baseline | Security + Integration | reviewed workflow/policy PR |
| P1 | assign owners and due dates to all open risks | Project Owner / PMO | updated `risks.csv` review |

