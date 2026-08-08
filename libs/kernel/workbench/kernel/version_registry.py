"""K3: durable schema version registry."""

import json
import threading
from pathlib import Path
from typing import Any


class VersionRegistryError(ValueError):
    """Raised when a version registry cannot be loaded or written safely."""


class VersionRegistry:
    def __init__(self, registry_file: Path):
        self.registry_file = registry_file
        self.versions: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self.registry_file.exists():
            return
        try:
            payload = json.loads(self.registry_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise VersionRegistryError(f"registry is unavailable or invalid: {self.registry_file}") from exc
        if not isinstance(payload, dict) or any(
            not isinstance(name, str)
            or not isinstance(versions, dict)
            or any(not isinstance(version, str) for version in versions)
            for name, versions in payload.items()
        ):
            raise VersionRegistryError(f"registry must map schema names to version maps: {self.registry_file}")
        self.versions = payload

    def _persist(self, versions: dict[str, dict[str, Any]]) -> None:
        try:
            self.registry_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.registry_file.with_name(f".{self.registry_file.name}.tmp")
            serialized = json.dumps(versions, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            temporary.write_text(serialized, encoding="utf-8")
            temporary.replace(self.registry_file)
        except (OSError, TypeError, ValueError) as exc:
            raise VersionRegistryError(f"registry could not be persisted: {self.registry_file}") from exc

    def register_schema(self, name: str, version: str, content: Any) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("schema name must be a non-empty string")
        if not isinstance(version, str) or not version:
            raise ValueError("schema version must be a non-empty string")
        with self._lock:
            updated = {schema: dict(versions) for schema, versions in self.versions.items()}
            updated.setdefault(name, {})[version] = content
            self._persist(updated)
            self.versions = updated
