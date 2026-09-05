# OmniSim pilot

This optional pilot talks only to an OmniSim World Harness on loopback. It
loads one vendor world in light mode, verifies a connected supervisor and a
finalized non-degraded Newton backend, restores the authored state, advances a
bounded number of steps, and records the raw vendor events in an atomic,
checksummed artifact.

```python
from pathlib import Path

from integrations.omnisim import OmniSimClient, OmniSimPilotRunner

result = OmniSimPilotRunner(OmniSimClient()).run(
    "projects/samples/demos/worlds/showcase/warehouse_husky.omniworld",
    Path("runs/omnisim"),
)
print(result.status, result.artifact_dir)
```

Start the separately installed simulator with `python -m omnisim harness`
before running the pilot. Every artifact is fixed to `evidence_class:
SIMULATION`, `physical_evidence: false`, `release_eligible: false`, and
`mapped_to_workbench_event_contract: false`.

This adapter does not replace `tools/scripts/sim_cli.py`, translate Workbench
scenario manifests, or promote OmniSim events into the existing event-log
contract. Those require a later compatibility slice with explicit mapping,
reset-isolation, arm, gripper, camera, and collision tests.
