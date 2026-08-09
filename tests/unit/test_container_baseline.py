from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UBUNTU_24_04_DIGEST = "sha256:561618e2c15bf2397621dd04f96926663a3b5616c189cf7e38db7e82f5c538ea"


def test_runtime_and_devcontainer_use_the_same_immutable_base() -> None:
    for relative_path in ("Dockerfile", ".devcontainer/Dockerfile"):
        first_line = (ROOT / relative_path).read_text(encoding="utf-8").splitlines()[0]
        assert first_line == f"FROM ubuntu@{UBUNTU_24_04_DIGEST}"
