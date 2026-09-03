# RLSOK Shadow pilot

This optional adapter invokes RLSOK's standalone `shadow` command and then its
`verify-evidence` command. It accepts blocked decisions as truthful results but
requires both `controllerGoalsAttempted: 0` and `hardwareSignalSent: false` in
the command summary and every evidence entry.

```python
from pathlib import Path

from integrations.rlsok import RlsokShadowRunner

result = RlsokShadowRunner().run(
    Path("integrations/rlsok/examples/workbench-release.shadow.yaml"),
    Path("integrations/rlsok/examples/workbench-pick-place-proposal.json"),
    Path("runs/rlsok/evidence.json"),
)
print(result.decision, result.evidence_ref)
```

The adapter never calls `rlsok run`, a ROS controller, or Workbench's
`ActionAdapter`. Standalone Shadow is a compatibility and evidence-format
probe; it is not the Hosted Cloud approval flow and does not prove this robot's
controller binding. The official live path still requires Ubuntu 24.04, ROS 2
Jazzy, Fast DDS, a supported controller graph, Cloud pairing, and independent
approval. RLSOK does not replace E-stop, watchdog, controller limits, motion
planning, or physical validation.

The checked-in Workbench fixture is bound to the current planner, contracts,
policy validator, execution controller, arm Xacro, controller configuration,
and a recorded five-test integration result. Its release status is `tested`,
not `approved`, so a current RLSOK runtime blocks it with
`release_not_approved` before considering dispatch. It also intentionally omits
an execution-configuration binding, which remains a second blocker after any
future independent approval.
