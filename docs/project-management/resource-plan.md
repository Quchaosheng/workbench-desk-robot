# Resource plan

This is a responsibility and capacity plan, not a claim that named staff are hired or available.

| Phase | Critical workstream | Accountable role | Supporting roles | Capacity rule |
|---|---|---|---|---|
| P1 | deterministic integration and formal Gazebo evaluation | Integration | Simulation, Motion, World Model, Perception | protect at least two coordinated owners for world/arm tuning; do not split untraceable parameter changes |
| P1 | release and security baseline | Integration | Security, Project Owner | separate code author, human reviewer, and human release decision |
| P1 | external reproduction | Project Owner | Documentation, Integration | three unique participants; maintain support boundaries defined by the protocol |
| P2 | task/scenario expansion | Runtime | World Model, Perception, Evaluation | parallelize by task family only after plugin/contracts are frozen |
| P2 | observability and performance | Integration | Performance, Backend | one owner for collection code and a separate business-metric reviewer |
| P2 | hardware input freeze | Hardware Owner | Procurement, Quality, Compliance | commercial/physical evidence cannot be replaced with software capacity |
| P3 | physical adapter integration | Hardware Owner | Motion, MCU, Linux, Safety | human owners control robot/control firmware and emergency-stop boundaries |
| P3 | hardware evaluation | Project Owner | Hardware, World Model, Evaluation | operator and independent audit capacity scheduled before the gate |

## Reallocation order

When critical work slips, move capacity from expression polish, replay visual polish, optional natural-language work, then optional local-model work. Never fund schedule recovery by weakening false-completion, collision, privilege, evaluation, or external-reproduction gates.

