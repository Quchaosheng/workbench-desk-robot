#!/usr/bin/env bash
set -euo pipefail

source_if_present() {
  if [[ -f "$1" ]]; then
    # shellcheck disable=SC1090
    set +u
    source "$1"
    set -u
  fi
}

# ROS 2 launch and Gazebo both create runtime state before the user command
# starts.  Keep those paths on the writable tmpfs even when the image is run
# read-only and the source tree is mounted read-only.
mkdir -p "${ROS_LOG_DIR:-/tmp/ros-log}" "${GZ_LOG_PATH:-/tmp/gz-log}" "${XDG_CACHE_HOME:-/tmp/cache}"

# Source order is a public development-container guarantee.
source_if_present /opt/ros/jazzy/setup.bash
source_if_present /opt/workbench_ws/install/setup.bash
source_if_present /workspace/install/setup.bash

export WORKBENCH_CONTAINER_PROFILE="${WORKBENCH_CONTAINER_PROFILE:-dashboard}"
case "$WORKBENCH_CONTAINER_PROFILE" in
  dashboard|ros-sim|gz-gui-x11|gz-gui-wayland|mujoco-gpu|hardware-shell) ;;
  *) echo "invalid WORKBENCH_CONTAINER_PROFILE=$WORKBENCH_CONTAINER_PROFILE" >&2; exit 2 ;;
esac

if [[ "$WORKBENCH_CONTAINER_PROFILE" == "hardware-shell" ]]; then
  /usr/local/bin/workbench-dds-config --output /tmp/workbench-fastdds.xml
  export FASTRTPS_DEFAULT_PROFILES_FILE=/tmp/workbench-fastdds.xml
fi

if [[ "$WORKBENCH_CONTAINER_PROFILE" != "dashboard" ]]; then
  /usr/local/bin/workbench-container-doctor --profile "$WORKBENCH_CONTAINER_PROFILE"
fi

exec "$@"
