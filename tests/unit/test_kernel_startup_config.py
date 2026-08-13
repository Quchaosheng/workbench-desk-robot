import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libs" / "kernel"))

from workbench.kernel.startup import CHECK_NAMES, SystemBootstrapper


def write_config(root: Path, payload: object) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "bootstrap.json").write_text(json.dumps(payload), encoding="utf-8")


def config(*, mode: str = "production", failed: str | None = None) -> dict:
    checks = {name: name != failed for name in CHECK_NAMES}
    return {
        "schemas": ["action"],
        "nodes": ["kernel"],
        "version": "1.0.0",
        "mode": mode,
        "checks": checks,
    }


def test_missing_config_fails_production_and_requires_explicit_offline_mode(tmp_path: Path) -> None:
    assert not SystemBootstrapper(tmp_path / "missing").bootstrap()

    bootstrapper = SystemBootstrapper(tmp_path / "missing", offline=True)
    assert bootstrapper.bootstrap()
    assert bootstrapper.config["mode"] == "offline"
    assert bootstrapper.config["nodes"] == ["kernel", "hardware", "sim"]


def test_configured_failed_check_blocks_bootstrap(tmp_path: Path) -> None:
    write_config(tmp_path, config(failed="contracts_valid"))
    assert not SystemBootstrapper(tmp_path).bootstrap()


def test_complete_production_checks_allow_bootstrap(tmp_path: Path) -> None:
    write_config(tmp_path, config())
    assert SystemBootstrapper(tmp_path).bootstrap()


def test_offline_and_production_modes_cannot_be_confused(tmp_path: Path) -> None:
    write_config(tmp_path, config(mode="offline"))
    assert not SystemBootstrapper(tmp_path).bootstrap()
    assert SystemBootstrapper(tmp_path, offline=True).bootstrap()

    write_config(tmp_path, config(mode="production"))
    assert not SystemBootstrapper(tmp_path, offline=True).bootstrap()


def test_malformed_or_unsafe_config_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "bootstrap.json").write_text("{bad-json}", encoding="utf-8")
    assert not SystemBootstrapper(tmp_path).bootstrap()

    write_config(
        tmp_path,
        {
            "schemas": ["action"],
            "nodes": ["kernel"],
            "version": "1.0.0",
            "mode": "production",
            "checks": {**{name: True for name in CHECK_NAMES}, "unknown": True},
        },
    )
    assert not SystemBootstrapper(tmp_path).bootstrap()

    write_config(tmp_path, {**config(), "schemas": []})
    assert not SystemBootstrapper(tmp_path).bootstrap()

    partial = config()
    partial["checks"].pop("memory_available")
    write_config(tmp_path, partial)
    assert not SystemBootstrapper(tmp_path).bootstrap()
