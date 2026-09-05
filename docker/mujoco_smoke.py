#!/usr/bin/env python3
"""Real MuJoCo EGL capability smoke, isolated from project domain contracts."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import subprocess

FORBIDDEN_RENDERERS = ("llvmpipe", "softpipe", "swrast", "software rasterizer")


def _gpu_summary() -> str:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,driver_version,uuid", "--format=csv,noheader"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return result.stdout.strip()


def main() -> int:
    if os.environ.get("MUJOCO_GL") != "egl":
        raise SystemExit("MUJOCO_GL=egl is required")

    import mujoco
    import numpy as np
    from OpenGL import GL

    seed = int(os.environ.get("WORKBENCH_SEED", "0"))
    steps = int(os.environ.get("WORKBENCH_MUJOCO_STEPS", "20"))
    if steps < 1 or steps > 10_000:
        raise SystemExit("WORKBENCH_MUJOCO_STEPS must be between 1 and 10000")
    rng = np.random.default_rng(seed)
    model = mujoco.MjModel.from_xml_string(
        """
        <mujoco>
          <option timestep="0.002"/>
          <visual><global offwidth="320" offheight="240"/></visual>
          <worldbody>
            <light pos="0 0 3"/>
            <camera name="smoke" pos="1.2 -1.2 0.8" xyaxes="1 1 0 -.4 .4 1"/>
            <geom type="plane" size="2 2 .1" rgba=".2 .25 .3 1"/>
            <body name="box" pos="0 0 .2">
              <freejoint/>
              <geom type="box" size=".08 .08 .08" mass=".1" rgba=".8 .2 .1 1"/>
            </body>
          </worldbody>
        </mujoco>
        """
    )
    data = mujoco.MjData(model)
    mujoco.mj_resetData(model, data)
    data.qvel[:3] = rng.uniform(-0.05, 0.05, size=3)
    for _ in range(steps):
        mujoco.mj_step(model, data)

    renderer = mujoco.Renderer(model, height=240, width=320)
    try:
        renderer.update_scene(data, camera="smoke")
        pixels = renderer.render()
        vendor_raw = GL.glGetString(GL.GL_VENDOR)
        renderer_raw = GL.glGetString(GL.GL_RENDERER)
        version_raw = GL.glGetString(GL.GL_VERSION)
    finally:
        renderer.close()
    vendor = vendor_raw.decode("utf-8", "replace") if vendor_raw else "unknown"
    gl_renderer = renderer_raw.decode("utf-8", "replace") if renderer_raw else "unknown"
    gl_version = version_raw.decode("utf-8", "replace") if version_raw else "unknown"
    renderer_identity = f"{vendor} {gl_renderer}".casefold()
    software = any(marker in renderer_identity for marker in FORBIDDEN_RENDERERS)
    nvidia = "nvidia" in renderer_identity
    finite = bool(np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all())
    nonblank = bool(pixels.size and int(pixels.max()) > int(pixels.min()))

    report = {
        "schema_version": "workbench-mujoco-container-smoke-v1",
        "status": "PASS" if finite and nonblank and nvidia and not software else "FAIL",
        "scope": "CONTAINER_CAPABILITY_SMOKE",
        "contract_output": False,
        "platform": platform.platform(),
        "gpu_tier": os.environ.get("WORKBENCH_GPU_TIER", "auto"),
        "image_digest": os.environ.get("WORKBENCH_IMAGE_DIGEST", "local-unpinned"),
        "commit": os.environ.get("WORKBENCH_COMMIT", "unknown"),
        "gpu": _gpu_summary(),
        "seed": seed,
        "steps": steps,
        "sim_time": data.time,
        "finite": finite,
        "image_nonblank": nonblank,
        "image_shape": list(pixels.shape),
        "image_sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
        "state_sha256": hashlib.sha256(data.qpos.tobytes()).hexdigest(),
        "mujoco": mujoco.__version__,
        "gl_backend": os.environ["MUJOCO_GL"],
        "gl_vendor": vendor,
        "gl_renderer": gl_renderer,
        "gl_version": gl_version,
        "software_renderer": software,
    }
    if not math.isfinite(float(data.time)):
        report["status"] = "FAIL"
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
