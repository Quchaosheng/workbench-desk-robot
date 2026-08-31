import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_doctor():
    path = ROOT / "docker/container-doctor.py"
    spec = importlib.util.spec_from_file_location("workbench_container_doctor", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _compose() -> dict:
    if shutil.which("docker") is None:
        import pytest

        pytest.skip("Docker CLI is intentionally not installed in the runtime container")
    result = subprocess.run(
        ["docker", "compose", "--profile", "*", "config", "--format", "json"],
        cwd=ROOT,
        env={**os.environ, "WORKBENCH_GPU_TIER": "auto"},
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_dockerfile_declares_three_gpu_dependency_layers() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    matrix = json.loads((ROOT / "docker/gpu-arch-matrix.json").read_text(encoding="utf-8"))

    assert set(matrix["dependency_layers"]) == {"gpu-runtime", "gpu-simulation", "gpu-validation"}
    for layer in matrix["dependency_layers"]:
        assert layer in dockerfile
    assert "nvidia/cuda:12.8.1-runtime-ubuntu24.04@sha256:" in dockerfile
    assert "nvidia-driver" not in dockerfile
    assert "nvidia-container-toolkit" not in dockerfile


def test_gpu_matrix_covers_rtx_30_40_50_with_name_and_compute_guards() -> None:
    matrix = json.loads((ROOT / "docker/gpu-arch-matrix.json").read_text(encoding="utf-8"))

    assert matrix["cuda_baseline"] == "12.8"
    assert matrix["minimum_driver_linux"] == "570.26"
    expected = {"rtx30": "8.6", "rtx40": "8.9", "rtx50": "12.0"}
    assert set(matrix["generations"]) == set(expected)
    for tier, capability in expected.items():
        generation = matrix["generations"][tier]
        assert capability in generation["compute_capabilities"]
        assert generation["name_patterns"]
        assert generation["physical_evidence_required"] is True


def test_gpu_detection_does_not_misclassify_datacenter_cards_by_compute_only() -> None:
    doctor = _load_doctor()

    assert doctor.detect_gpu_tier("NVIDIA GeForce RTX 3080", "8.6") == "rtx30"
    assert doctor.detect_gpu_tier("NVIDIA GeForce RTX 4090", "8.9") == "rtx40"
    assert doctor.detect_gpu_tier("NVIDIA GeForce RTX 5090", "12.0") == "rtx50"
    assert doctor.detect_gpu_tier("NVIDIA A10", "8.6") is None
    assert doctor.detect_gpu_tier("NVIDIA L40S", "8.9") is None


def test_compose_keeps_dashboard_cpu_safe_and_gpu_profiles_explicit() -> None:
    services = _compose()["services"]
    dashboard = services["dashboard"]

    assert "profiles" not in dashboard
    assert "gpus" not in dashboard
    assert "devices" not in dashboard
    assert "cap_add" not in dashboard
    assert dashboard["read_only"] is True
    assert dashboard["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in dashboard["security_opt"]

    for profile in ("ros-sim", "gz-gui-x11", "gz-gui-wayland", "mujoco-gpu"):
        service = services[profile]
        assert service["profiles"] == [profile]
        assert service["gpus"] == [{"count": -1}]
        assert service["environment"]["NVIDIA_DRIVER_CAPABILITIES"] == "compute,utility,graphics"

    hardware = services["hardware-shell"]
    assert hardware["profiles"] == ["hardware-shell"]
    assert hardware["network_mode"] == "host"
    assert hardware["cap_add"] == ["NET_RAW"]

    compose_text = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "privileged" not in compose_text
    assert "NET_ADMIN" not in compose_text
    assert "xhost +" not in compose_text


def test_source_is_read_only_and_colcon_outputs_are_named_volumes() -> None:
    compose_text = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    devcontainer = json.loads((ROOT / ".devcontainer/devcontainer.json").read_text(encoding="utf-8"))

    assert ".:/workspace/src:ro" in compose_text
    for name in ("workbench-build", "workbench-install", "workbench-log"):
        assert name in compose_text
    assert devcontainer["build"]["dockerfile"] == "../Dockerfile"
    assert "readonly" in devcontainer["workspaceMount"]
    for name in ("workbench-dev-build", "workbench-dev-install", "workbench-dev-log"):
        assert any(name in mount for mount in devcontainer["mounts"])


def test_runtime_tmpfs_and_simulation_paths_are_writable_for_runtime_user() -> None:
    compose_text = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert (
        "/home/workbench/.ros:size=64m,mode=700,uid=${WORKBENCH_UID:-10001},gid=${WORKBENCH_GID:-10001}"
        in compose_text
    )
    assert (
        "/home/workbench/.cache:size=256m,mode=700,uid=${WORKBENCH_UID:-10001},gid=${WORKBENCH_GID:-10001}"
        in compose_text
    )
    for variable, value in (
        ("HOME", "/home/workbench"),
        ("ROS_LOG_DIR", "/tmp/ros-log"),
        ("GZ_LOG_PATH", "/tmp/gz-log"),
        ("XDG_CACHE_HOME", "/tmp/cache"),
        ("GZ_SIM_RESOURCE_PATH", "/opt/ros/jazzy/share:/opt/workbench_ws/install/share:/workspace/install/share"),
    ):
        assert f"{variable}: {value}" in compose_text


def test_entrypoint_sources_ros_then_image_then_development_install() -> None:
    entrypoint = (ROOT / "docker/entrypoint.sh").read_text(encoding="utf-8")

    assert "set +u" in entrypoint
    assert entrypoint.index("set +u") < entrypoint.index('source "$1"') < entrypoint.index("set -u")
    ros = entrypoint.index("/opt/ros/jazzy/setup.bash")
    image_install = entrypoint.index("/opt/workbench_ws/install/setup.bash")
    development_install = entrypoint.index("/workspace/install/setup.bash")
    assert ros < image_install < development_install < entrypoint.index('exec "$@"')
    assert "/opt/workbench_source/robot/control/install/setup.bash" not in entrypoint


def test_mujoco_smoke_requires_real_egl_pixels_and_rejects_software_renderer() -> None:
    smoke = (ROOT / "docker/mujoco_smoke.py").read_text(encoding="utf-8")

    assert "mujoco.Renderer" in smoke
    assert "image_sha256" in smoke
    assert "CONTAINER_CAPABILITY_SMOKE" in smoke
    assert "llvmpipe" in smoke
    assert '"nvidia" in renderer_identity' in smoke
    assert "image_digest" in smoke


def test_gazebo_render_smoke_requires_nvidia_egl_vendor() -> None:
    smoke = (ROOT / "docker/gazebo_render_smoke.sh").read_text(encoding="utf-8")

    assert "eglinfo -B -p surfaceless" in smoke
    assert "NVIDIA EGL vendor was not evidenced" in smoke
    assert "llvmpipe" in smoke


def test_sim_smoke_waits_for_all_controllers_and_bounds_probe() -> None:
    smoke = (ROOT / "docker/sim_smoke.sh").read_text(encoding="utf-8")

    assert "controllers_ready=false" in smoke
    for controller in ("joint_state_broadcaster", "arm_trajectory_controller", "gripper_controller"):
        assert f"^{controller}.*active" in smoke
    assert 'WORKBENCH_PHASE2_TIMEOUT:-180' in smoke


def test_hardware_profile_keeps_devices_and_sros2_fail_closed() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    doctor = (ROOT / "docker/container-doctor.py").read_text(encoding="utf-8")

    assert "WORKBENCH_SERIAL_DEVICE" in compose
    assert "WORKBENCH_CAN_INTERFACE" in compose
    assert "WORKBENCH_DDS_INTERFACE" in compose
    assert "ROS_SECURITY_STRATEGY: Enforce" in compose
    assert "/run/sros2/keystore:ro" in compose
    assert "/dev/serial/by-id/" in doctor
    assert "is_char_device" in doctor
    assert "interfaceWhiteList" in (ROOT / "docker/dds_config.py").read_text(encoding="utf-8")


def test_host_doctor_requires_at_least_one_gpu_row_for_driver_pass() -> None:
    doctor = (ROOT / "docker/host_doctor.py").read_text(encoding="utf-8")

    assert "bool(gpu_rows)" in doctor


def test_gpu_doctor_requires_nvidia_egl_vendor_evidence() -> None:
    doctor = (ROOT / "docker/container-doctor.py").read_text(encoding="utf-8")

    assert "egl_vendor_files" in doctor
    assert "NVIDIA EGL vendor JSON is unavailable" in doctor


def test_container_python_test_uses_writable_copy_and_excludes_host_docker_tests() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    target = makefile.split("container-python-test:\n", 1)[1].split("\n\n", 1)[0]

    assert "mktemp -d /tmp/workbench-python-test.XXXXXX" in target
    assert "cp -a /workspace/src/." in target
    assert "--ignore=tests/unit/test_multi_host_deployment.py" in target
    assert "--cache-dir" not in target


def test_colcon_test_and_result_logs_use_writable_volume() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    target = makefile.split("container-colcon-test:\n", 1)[1].split("\n\n", 1)[0]

    assert target.count("colcon --log-base /workspace/log") == 2
    assert "test-result --test-result-base /workspace/build" in target
