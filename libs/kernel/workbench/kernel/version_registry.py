"""K3: durable schema version registry."""

import fcntl
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class VersionRegistryError(ValueError):
    """Raised when a version registry cannot be loaded or written safely."""


class VersionConflictError(VersionRegistryError):
    """Raised when a published schema version is registered with new content."""


class VersionRegistry:
    def __init__(self, registry_file: Path):
        self.registry_file = registry_file
        self.versions: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._load()

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.registry_file.exists():
            return {}
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
        return payload

    def _load(self) -> None:
        self.versions = self._read()

    @contextmanager
    def _file_lock(self):
        """Serialize registry writers across threads and processes."""
        try:
            self.registry_file.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self.registry_file.with_name(f".{self.registry_file.name}.lock")
            with lock_path.open("a+b") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            raise VersionRegistryError(f"registry could not be locked: {self.registry_file}") from exc

    def _persist(self, versions: dict[str, dict[str, Any]]) -> None:
        temporary_name: str | None = None
        try:
            self.registry_file.parent.mkdir(parents=True, exist_ok=True)
            serialized = json.dumps(versions, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                prefix=f".{self.registry_file.name}.",
                suffix=".tmp",
                dir=self.registry_file.parent,
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(serialized)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, self.registry_file)
            temporary_name = None
        except (OSError, TypeError, ValueError) as exc:
            raise VersionRegistryError(f"registry could not be persisted: {self.registry_file}") from exc
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass

    def register_schema(self, name: str, version: str, content: Any) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("schema name must be a non-empty string")
        if not isinstance(version, str) or not version:
            raise ValueError("schema version must be a non-empty string")
        with self._lock, self._file_lock():
            current = self._read()
            registered = current.get(name, {})
            if version in registered:
                if registered[version] == content:
                    self.versions = current
                    return
                raise VersionConflictError(
                    f"schema {name!r} version {version!r} is already registered with different content"
                )
            updated = {schema: dict(versions) for schema, versions in current.items()}
            updated.setdefault(name, {})[version] = content
            self._persist(updated)
            self.versions = updated
