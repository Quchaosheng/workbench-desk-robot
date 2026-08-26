import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMMUTABLE_UBUNTU_BASE = re.compile(r"^FROM ubuntu@sha256:[0-9a-f]{64}$")


def test_runtime_and_devcontainer_use_the_same_immutable_base() -> None:
    first_lines = {
        (ROOT / relative_path).read_text(encoding="utf-8").splitlines()[0]
        for relative_path in ("Dockerfile", ".devcontainer/Dockerfile")
    }
    assert len(first_lines) == 1
    assert IMMUTABLE_UBUNTU_BASE.fullmatch(first_lines.pop())


def test_runtime_container_copies_installable_workbench_packages_before_install() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    install_offset = dockerfile.index("python -m pip install --no-compile .")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_directories = pyproject["tool"]["setuptools"]["package-dir"].values()
    source_roots = {"/".join(Path(directory).parts[:2]) for directory in package_directories}

    for source_root in sorted(source_roots):
        package_copy = f"COPY {source_root} ./{source_root}"
        assert dockerfile.index(package_copy) < install_offset
