import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libs" / "kernel"))

from workbench.kernel.version_registry import VersionConflictError, VersionRegistry, VersionRegistryError


def test_registry_survives_reopen_and_keeps_versions_separate(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    registry = VersionRegistry(path)
    registry.register_schema("action", "1.0.0", {"type": "object"})
    registry.register_schema("action", "1.1.0", {"type": "object", "required": ["id"]})
    registry.register_schema("result", "1.0.0", {"type": "object"})

    reopened = VersionRegistry(path)
    assert reopened.versions == {
        "action": {
            "1.0.0": {"type": "object"},
            "1.1.0": {"required": ["id"], "type": "object"},
        },
        "result": {"1.0.0": {"type": "object"}},
    }


def test_invalid_registry_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"action": ["not-a-version-map"]}), encoding="utf-8")

    with pytest.raises(VersionRegistryError, match="must map schema names"):
        VersionRegistry(path)


def test_unserializable_content_does_not_replace_in_memory_state(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    registry = VersionRegistry(path)
    with pytest.raises(VersionRegistryError, match="could not be persisted"):
        registry.register_schema("action", "1.0.0", {"bad": {1, 2}})
    assert registry.versions == {}
    assert not path.exists()


def test_identical_registration_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    registry = VersionRegistry(path)
    content = {"type": "object", "required": ["id"]}
    registry.register_schema("action", "1.0.0", content)
    before = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns

    registry.register_schema("action", "1.0.0", {"type": "object", "required": ["id"]})

    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == before_mtime
    assert VersionRegistry(path).versions["action"]["1.0.0"] == content


def test_conflicting_registration_is_rejected_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    registry = VersionRegistry(path)
    registry.register_schema("action", "1.0.0", {"required": ["id"]})
    before = path.read_bytes()

    with pytest.raises(VersionConflictError, match="already registered"):
        registry.register_schema("action", "1.0.0", {"required": ["target"]})

    assert registry.versions["action"]["1.0.0"] == {"required": ["id"]}
    assert path.read_bytes() == before
    assert not path.with_name(f".{path.name}.tmp").exists()
    assert VersionRegistry(path).versions == registry.versions
