from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UBUNTU_24_04_DIGEST = "sha256:678c6550cc43645e08669028bc177f50be4e7c5b8cca677067b1914d4afc7a03"


def test_runtime_and_devcontainer_use_the_same_immutable_base() -> None:
    for relative_path in ("Dockerfile", ".devcontainer/Dockerfile"):
        first_line = (ROOT / relative_path).read_text(encoding="utf-8").splitlines()[0]
        assert first_line == f"FROM ubuntu@{UBUNTU_24_04_DIGEST}"


def test_runtime_container_copies_installable_workbench_packages_before_install() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    install_offset = dockerfile.index("python -m pip install --no-compile .")

    for package_copy in (
        "COPY libs/hardware ./libs/hardware",
        "COPY libs/kernel ./libs/kernel",
    ):
        assert dockerfile.index(package_copy) < install_offset
