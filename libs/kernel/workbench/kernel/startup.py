"""K9-K10: startup configuration and fail-closed readiness checks."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CHECK_NAMES = (
    "schema_compatibility",
    "version_middleware",
    "disk_space",
    "all_nodes_online",
    "event_store_ready",
    "lifecycle_configured",
    "contracts_valid",
    "dependencies_resolved",
    "config_loaded",
    "memory_available",
)
REQUIRED_CONFIG_KEYS = ("schemas", "nodes", "version", "mode", "checks")
DEFAULT_CONFIG = {
    "schemas": ["action", "state", "result"],
    "nodes": ["kernel", "hardware", "sim"],
    "version": "1.0.0",
    "mode": "offline",
    "checks": {name: True for name in CHECK_NAMES},
}


class StartupChecklist:
    def __init__(self, checks: Mapping[str, bool]):
        self._validate_checks(checks)
        if set(checks) != set(CHECK_NAMES):
            missing = set(CHECK_NAMES) - set(checks)
            raise ValueError(f"startup checks must be complete; missing: {sorted(missing)}")
        self.checks = dict(checks)

    @staticmethod
    def _validate_checks(checks: Mapping[str, Any]) -> bool:
        unknown = set(checks) - set(CHECK_NAMES)
        if unknown:
            raise ValueError(f"unknown startup checks: {sorted(unknown)}")
        if any(type(value) is not bool for value in checks.values()):
            raise ValueError("startup check values must be boolean")
        return True

    def verify_all(self) -> bool:
        return all(self.checks.values())


class SystemBootstrapper:
    def __init__(self, config_dir: Path, *, offline: bool = False):
        self.config_dir = Path(config_dir)
        self.offline = offline
        self.config: dict[str, Any] = {}

    @staticmethod
    def _valid_config(config: Any) -> bool:
        if not isinstance(config, dict):
            return False
        if any(key not in config for key in REQUIRED_CONFIG_KEYS):
            return False
        if not isinstance(config["version"], str) or not config["version"]:
            return False
        if config["mode"] not in {"production", "offline"}:
            return False
        checks = config["checks"]
        if not isinstance(checks, Mapping):
            return False
        try:
            StartupChecklist(checks)
        except ValueError:
            return False
        if any(
            not isinstance(config[key], list)
            or not config[key]
            or any(not isinstance(item, str) or not item for item in config[key])
            for key in ("schemas", "nodes")
        ):
            return False
        return True

    def load_config(self) -> bool:
        config_path = self.config_dir / "bootstrap.json"
        if not config_path.exists():
            if not self.offline:
                return False
            self.config = {**DEFAULT_CONFIG, "checks": dict(DEFAULT_CONFIG["checks"])}
            return True
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        if not self._valid_config(config):
            return False
        if (config["mode"] == "offline") != self.offline:
            return False
        self.config = config
        return True

    def bootstrap(self) -> bool:
        if not self.load_config():
            return False
        return StartupChecklist(self.config["checks"]).verify_all()
