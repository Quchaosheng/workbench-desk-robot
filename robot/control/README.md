# Robot control (Owner: Motion)

Implement semantic action adapters and ActionResult production here. This module
receives validated actions; it must reject raw joint commands from Agent Runtime.

Detailed construction plan and acceptance gates: `PLAN.md` (kept local, not in
the public repo).

## Package: `workbench_motion`

ROS 2 (Jazzy) `ament_python` package. **Phase 1** delivers UR5e + Robotiq 2F-85
arm composition into the world model, MoveIt integration, and a reachability gate
(≥95% IK success over block + tray regions):

```
workbench_motion/
  package.xml            # ament_python; ROS runtime deps (rclpy, moveit, ur/robotiq, ...)
  setup.py / setup.cfg   # colcon entry points: scaffold_node, reachability_check
  resource/…             # ament index marker
  workbench_motion/
    logging_setup.py     # unified stdlib logging: run_id/action_id, no print
    evidence.py          # ExecutionEvent + EvidenceSink interface + FakeEvidenceSink
    scaffold_node.py     # minimal node for the empty-world self test
    reachability.py      # pure-logic IK sampling, region scoring (ROS-free, unit-tested)
    reachability_check.py  # ROS console script: MoveIt /compute_ik, write eval JSON
  config/
    arm.yaml             # swap surface: group names, links, joint count, base placement
    arm_on_workbench.urdf.xacro  # UR5e + Robotiq + workbench world composition
    moveit/              # SRDF, kinematics (TRAC-IK), joint_limits, OMPL pipeline
  launch/
    scaffold.launch.py   # phase-0 empty-world self test
    move_group.launch.py # MoveIt move_group for the composed arm (phase 1)
  test/                  # pytest unit tests (evidence, logging, reachability logic)
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

### Prerequisites (phase 1)

Install ROS 2 Jazzy, UR/Robotiq descriptions, and MoveIt with TRAC-IK:

```bash
sudo apt-get update && sudo apt-get install -y \
  ros-jazzy-moveit \
  ros-jazzy-moveit-py \
  ros-jazzy-trac-ik-kinematics-plugin \
  ros-jazzy-ur-moveit-config \
  ros-jazzy-ur-simulation-gz \
  ros-jazzy-gz-ros2-control \
  ros-jazzy-controller-manager \
  ros-jazzy-joint-trajectory-controller \
  ros-jazzy-robotiq-controllers
```

(`ros-jazzy-desktop`, `xacro`, `ur-description`, `robotiq-description` assumed
already installed.)

### Pure-Python unit tests (no ROS needed)

From `robot/control/`:

```bash
uv sync
uv run pytest        # -> workbench_motion/test
```

> Works whether or not a ROS 2 env is sourced. When ROS is sourced, its pytest
> plugins (`launch_testing`, `launch_ros`, `ament_*`) leak in via `PYTHONPATH`
> and would fail to import inside this isolated venv; the pytest config blocks
> them by name. Bulletproof fallback if that ever drifts:
> `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest`.

### ROS build + structural validation

Needs ROS 2 Jazzy sourced; run from a colcon workspace whose `src/` contains
this package:

```bash
# Build
colcon build --packages-select workbench_motion
source install/setup.bash

# Validate composed URDF (single tree rooted at world, no errors). The composed
# xacro finds the vendored workbench world via $(find workbench_motion), so this
# works from either the installed share or the source tree once the workspace is
# sourced — no --symlink-install required.
xacro $(ros2 pkg prefix workbench_motion)/share/workbench_motion/config/arm_on_workbench.urdf.xacro > /tmp/wb_arm.urdf
check_urdf /tmp/wb_arm.urdf

# Launch move_group (headless, for reachability check)
ros2 launch workbench_motion move_group.launch.py

# In another shell (after move_group is up). --timeout 0.05 matches the solver
# timeout in config/moveit/kinematics.yaml. The default --output is a relative
# path that anchors to the git repo root (not the shell's cwd), so the JSON lands
# in the repo even when run from robot/control:
source install/setup.bash
ros2 run workbench_motion reachability_check --seed 0 --samples 20 --yaws 12 --timeout 0.05
# writes docs/evaluation/phase1-reachability.json; exits 0 if ≥95% both regions.
# Pass --output <path> to override (an absolute path is used verbatim).
```

> **Status (verified 2026-08-09, MoveIt + TRAC-IK on Jazzy):** gate PASSES.
> block 20/20 and tray 20/20 graspable (≥95%), pure-IK reach 100% both regions,
> collision-free yaw margins block 8–11 / tray 11–12. Stable across seeds 0/7/42.
> The metric is *position-level*: a position counts as graspable if ≥1 top-down
> approach yaw is collision-free and IK-valid (a parallel-jaw grasp is symmetric
> mod 180° and the planner picks the yaw). `docs/evaluation/phase1-reachability.json`
> holds the seed-0 run. Reproduce with the two commands above.

Phase-0 empty-world self test (still works):

```bash
ros2 launch workbench_motion scaffold.launch.py
```

### Swapping the arm (phase 1 config surface)

Arm-specific identifiers are isolated in **`config/arm.yaml`** and xacro args,
never hard-coded in adapter logic. A later swap to Panda (or another arm) touches:

1. **`config/arm.yaml`**: planning group, base/ee/gripper links, joint count, base placement.
2. **`config/arm_on_workbench.urdf.xacro`**: xacro includes + macro instantiation (UR → Panda).
3. **`config/moveit/*`**: SRDF groups, kinematics, joint_limits (re-generate or hand-edit).
4. **`package.xml`**: swap `ur_description` + `robotiq_description` → `franka_description`.
5. **Reachability re-validation**: run `reachability_check` with the new arm and verify ≥95%.

Runtime Python (`reachability_check.py` and future motion nodes) reads
`config/arm.yaml` via `workbench_motion.arm_config.load_arm_config()` — the
planning group, IK tip and base frame are **not** hard-coded. CLI flags can
override for ad-hoc probing, but with no flags the values come from arm.yaml
(regression-guarded in `test/test_arm_config.py`). Note the SRDF and the xacro
macro instantiation are still hand-edited per arm — that is the "config edit",
not a Python edit. Acceptance: the swap touches no `.py` files under
`workbench_motion/workbench_motion/`.
