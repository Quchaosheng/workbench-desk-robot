# fault_injection

Scripts and config for injecting faults into simulation runs.

Four supported fault classes (v0.1):
- `occlusion`      object partially blocked from camera
- `target_moved`   object displaced mid-task
- `grasp_failed`   gripper closes but drops object
- `low_confidence` camera returns detection with confidence < threshold

Fault injection is declared in the scenario manifest (`fault_type` field)
and triggered by `services/world_model` via registered hooks.

Adding a fault class:
1. Add the type string to `scenario.schema.json` enum
2. Implement the hook in `services/world_model/workbench_world_model/faults.py`
3. Add a scenario manifest using the new type
4. Add a test verifying the fault is triggered
