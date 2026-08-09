# Evidence Index

| Claim | Required evidence | Owner |
|---|---|---|
| Task completed | Observation + ActionResult + verifier rule | World Model |
| Action safe | planner/controller/MCU records | Motion + MCU |
| Scenario valid | manifest + validator output | Simulation |
| Metric passed | raw events + fixed calculation script | Product Owner + World Model |
| Local model usable | golden set + `runs/performance/local-model-plan.json` + latency/resource report | Runtime + Perception |
| Startup target passed | `runs/performance/startup-cold.json` and cached startup report | Integration |
| Release reproducibility | SPDX SBOM + `release-manifest.json` with registry digest | Product Owner + Integration |
| Real hardware timing | unified hardware JSONL + hash-verified operator manifest | Hardware Owner |
| External cold start | three filled participant records and validator output | Product Owner |
