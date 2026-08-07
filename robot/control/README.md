# Robot control (Owner: Motion)

Implement semantic action adapters and ActionResult production here. This module
receives validated actions; it must reject raw joint commands from Agent Runtime.

Detailed construction plan and acceptance gates: `PLAN.md` (kept local, not in
the public repo).

## Package: `workbench_motion`

ROS 2 (Jazzy) `ament_python` package. Phase 0 delivers the engineering scaffold
only — no arm, no MoveIt, no grasp logic yet:

```
workbench_motion/
  package.xml            # ament_python; ROS runtime deps (rclpy, launch, ...) via rosdep
  setup.py / setup.cfg   # colcon entry point: scaffold_node
  resource/…             # ament index marker
  workbench_motion/
    logging_setup.py     # unified stdlib logging: run_id/action_id, no print
    evidence.py          # ExecutionEvent + EvidenceSink interface + FakeEvidenceSink
    scaffold_node.py     # minimal node for the empty-world self test
  launch/scaffold.launch.py   # empty-world self test, no external bringup
  test/                  # pytest unit tests (evidence + logging)
```

### Two toolchains, on purpose

- **Pure-Python layer** (evidence, logging, contracts, tests, tooling) is managed
  by **uv**, scoped to this module (`robot/control/pyproject.toml` + `uv.lock`).
  Per `PLAN.md`, a root-level `uv.lock` needs Linux/Integration sign-off; until
  then uv stays package-local, which is what this env is.
- **ROS 2 runtime** (rclpy, launch, launch_ros, and later moveit2 / ros2_control)
  is apt/rosdep-managed and declared in `workbench_motion/package.xml`. uv does
  not manage these.

`evidence.py` and `logging_setup.py` deliberately have **no ROS imports**, and
`scaffold_node.py` imports `rclpy` lazily inside `main()`, so the pure-Python
parts import and test under a plain uv venv with no ROS installed.

## Build & test

Pure-Python unit tests (no ROS needed), from `robot/control/`:

```bash
uv sync
uv run pytest        # -> workbench_motion/test  (10 tests)
```

> Works whether or not a ROS 2 env is sourced. When ROS is sourced, its pytest
> plugins (`launch_testing`, `launch_ros`, `ament_*`) leak in via `PYTHONPATH`
> and would fail to import inside this isolated venv; the pytest config blocks
> them by name. Bulletproof fallback if that ever drifts:
> `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest`.

ROS build + package visibility + launch self test (needs ROS 2 Jazzy sourced;
run from a colcon workspace whose `src/` contains this package):

```bash
colcon build --packages-select workbench_motion
ros2 pkg list | grep workbench_motion
ros2 launch workbench_motion scaffold.launch.py   # empty-world self test
```

> The uv venv used to *run* the node must see `/opt/ros/jazzy` site-packages so
> apt `rclpy` is importable — create it with `--system-site-packages` or point at
> the ROS site-packages. The pure-Python tests above do not need this.

### Swapping the arm later (forward pointer)

Arm-specific names (planning group, base/end-effector/gripper links, joint count)
are kept in config/params, never hard-coded in adapter logic, so a later arm swap
touches config only. Details land with phase 1.
