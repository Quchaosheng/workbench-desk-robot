# Quality metrics

| Metric | Target | Eligible source | Owner | Gate behavior |
|---|---:|---|---|---|
| false completion | 0 | formal raw event logs plus independent audit | World Model + Project Owner | any occurrence blocks release |
| collision / joint-limit violation | 0 | Gazebo or hardware safety logs | Motion + Safety | any occurrence blocks release |
| raw joint control from model | 0 | planner/tool boundary tests and logs | Runtime | any occurrence blocks release |
| critical event field completeness | 100% | contract validator plus raw events | World Model | missing fields block affected claim |
| fixed-script grasp success | >=90% simulation / >=70% real | frozen-scene physical runs | Motion + Simulation/Hardware | below target stops the phase gate |
| verified task completion rate | >=80% | formal evaluation report linked to raw runs | Project Owner + World Model | below target stops the phase gate |
| recovery success | >=70% | formal failure scenarios | World Model + Motion | below target requires mitigation or scope decision |
| task latency P95 | <120s P1 / <60s P2 | formal evaluation telemetry | Performance | forecast and optimize; no fixture substitution |
| scenario reproducibility | 100% | same-seed validator and materialized hashes | Simulation | drift blocks comparison |
| external cold start | >=2 of 3 within 60 min | three unique validated participant records | Project Owner | absent records mean UNKNOWN/RED |
| required CI checks | 100% pass | GitHub Actions commit status | Integration | failed required check blocks merge |
| team delivery satisfaction | >=4/5 | anonymous monthly pulse with response count | PMO | report only after a real survey |

Use `UNKNOWN` when the eligible source is missing. Planning values, fixtures, screenshots, and generated templates cannot populate physical metrics.

