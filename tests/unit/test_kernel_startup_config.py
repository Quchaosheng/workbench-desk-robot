import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libs" / "kernel"))

from workbench.kernel.startup import SystemBootstrapper


def write_config(root: Path, payload: object) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "bootstrap.json").write_text(json.dumps(payload), encoding="utf-8")


def test_missing_config_keeps_offline_defaults(tmp_path: Path) -> None:
    bootstrapper = SystemBootstrapper(tmp_path / "missing")
    assert bootstrapper.bootstrap()
    assert bootstrapper.config["nodes"] == ["kernel", "hardware", "sim"]


def test_configured_failed_check_blocks_bootstrap(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        {
            "schemas": ["action"],
            "nodes": ["kernel"],
            "version": "1.0.0",
            "checks": {"contracts_valid": False},
        },
    )
    assert not SystemBootstrapper(tmp_path).bootstrap()


def test_malformed_or_unsafe_config_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "bootstrap.json").write_text("{bad-json}", encoding="utf-8")
    assert not SystemBootstrapper(tmp_path).bootstrap()

    write_config(
        tmp_path,
        {"schemas": ["action"], "nodes": ["kernel"], "version": "1.0.0", "checks": {"unknown": True}},
    )
    assert not SystemBootstrapper(tmp_path).bootstrap()

    write_config(tmp_path, {"schemas": [], "nodes": ["kernel"], "version": "1.0.0"})
    assert not SystemBootstrapper(tmp_path).bootstrap()
