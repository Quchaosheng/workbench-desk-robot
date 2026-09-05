#!/usr/bin/env bash
set -euo pipefail

world=/usr/share/workbench/container/camera-rendering-smoke.sdf
log=/tmp/workbench-gazebo-render.log
image=/tmp/workbench-gazebo-image.txt

mkdir -p "${GZ_LOG_PATH:-/tmp/gz-log}" "${XDG_CACHE_HOME:-/tmp/cache}" "${ROS_LOG_DIR:-/tmp/ros-log}"

gz sim -s -r -v 4 "$world" >"$log" 2>&1 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true; wait "$server_pid" 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  if ! kill -0 "$server_pid" 2>/dev/null; then
    tail -100 "$log" >&2
    echo '{"status":"NOT_EXECUTED","reason":"Gazebo server exited before producing an image"}' >&2
    exit 2
  fi
  if timeout 3 gz topic -e -t /workbench/camera/image -n 1 >"$image" 2>/dev/null && [[ -s "$image" ]]; then
    break
  fi
  sleep 1
done

if [[ ! -s "$image" ]]; then
  tail -100 "$log" >&2
  echo '{"status":"NOT_EXECUTED","reason":"Gazebo camera produced no image"}' >&2
  exit 2
fi
if rg -qi 'llvmpipe|softpipe|swrast|software rasterizer' "$log"; then
  echo '{"status":"FAIL","reason":"software renderer detected"}' >&2
  exit 2
fi
egl_info=$(eglinfo -B -p surfaceless 2>/dev/null || true)
if ! printf '%s\n%s\n' "$log" "$egl_info" | rg -qi 'nvidia'; then
  echo '{"status":"NOT_EXECUTED","reason":"NVIDIA EGL vendor was not evidenced"}' >&2
  exit 2
fi
checksum=$(sha256sum "$image" | awk '{print $1}')
printf '{"schema_version":"workbench-gazebo-render-smoke-v1","status":"PASS","scope":"CONTAINER_CAPABILITY_SMOKE","image_sha256":"%s"}\n' "$checksum"
