#!/usr/bin/env bash
set -euo pipefail

log=/workspace/log/gazebo-phase2.log
evidence=/workspace/log/phase2-controllers.json
ros2 launch workbench_motion sim_control.launch.py >"$log" 2>&1 &
launch_pid=$!
trap 'kill "$launch_pid" 2>/dev/null || true; wait "$launch_pid" 2>/dev/null || true' EXIT

controllers=""
controllers_ready=false
for _ in $(seq 1 60); do
  if ! kill -0 "$launch_pid" 2>/dev/null; then
    tail -120 "$log" >&2
    echo '{"status":"NOT_EXECUTED","reason":"Gazebo launch exited before controllers became active"}' >&2
    exit 2
  fi
  if controllers=$(ROS2CLI_USE_DAEMON=0 timeout 5 ros2 control list_controllers --spin-time 2 2>/dev/null); then
    if printf '%s\n' "$controllers" | rg -q '^joint_state_broadcaster.*active' \
      && printf '%s\n' "$controllers" | rg -q '^arm_trajectory_controller.*active' \
      && printf '%s\n' "$controllers" | rg -q '^gripper_controller.*active'; then
      controllers_ready=true
      break
    fi
  fi
  sleep 1
done

if [[ "$controllers_ready" != true ]]; then
  printf '%s\n' "$controllers" >&2
  tail -120 "$log" >&2
  echo '{"status":"NOT_EXECUTED","reason":"all required controllers did not become active"}' >&2
  exit 2
fi
printf '%s\n' "$controllers"
ROS2CLI_USE_DAEMON=0 timeout 15 ros2 topic echo /clock --once >/dev/null
cd /workspace/src
timeout "${WORKBENCH_PHASE2_TIMEOUT:-180}" ros2 run workbench_motion phase2_probe --output "$evidence"
