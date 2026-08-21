import json
import multiprocessing
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libs" / "kernel"))

from workbench.kernel.version_registry import VersionConflictError, VersionRegistry, VersionRegistryError


class SlowRegistry(VersionRegistry):
    def _persist(self, versions: dict[str, dict[str, object]]) -> None:
        time.sleep(0.01)
        super()._persist(versions)


def _register_from_process(path: str, index: int) -> None:
    SlowRegistry(Path(path)).register_schema("process", str(index), {"index": index})


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


def test_failed_replace_keeps_original_and_removes_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "registry.json"
    registry = VersionRegistry(path)
    registry.register_schema("action", "1.0.0", {"required": ["id"]})
    before = path.read_bytes()

    def fail_replace(source: str, destination: Path) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr("workbench.kernel.version_registry.os.replace", fail_replace)
    with pytest.raises(VersionRegistryError, match="could not be persisted"):
        registry.register_schema("result", "1.0.0", {"type": "object"})

    assert path.read_bytes() == before
    assert registry.versions == {"action": {"1.0.0": {"required": ["id"]}}}
    assert list(tmp_path.glob(f".{path.name}.*.tmp")) == []


def test_stale_instances_merge_disjoint_schema_versions(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    first = VersionRegistry(path)
    second = VersionRegistry(path)

    first.register_schema("action", "1.0.0", {"type": "object"})
    second.register_schema("result", "1.0.0", {"type": "object"})

    assert VersionRegistry(path).versions == {
        "action": {"1.0.0": {"type": "object"}},
        "result": {"1.0.0": {"type": "object"}},
    }


def test_stale_instance_rechecks_conflicting_version(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    first = VersionRegistry(path)
    second = VersionRegistry(path)
    first.register_schema("action", "1.0.0", {"required": ["id"]})

    with pytest.raises(VersionConflictError, match="already registered"):
        second.register_schema("action", "1.0.0", {"required": ["target"]})

    assert VersionRegistry(path).versions == {"action": {"1.0.0": {"required": ["id"]}}}


def test_concurrent_process_registrations_are_not_lost(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    with multiprocessing.get_context("fork").Pool(4) as processes:
        processes.starmap(_register_from_process, [(str(path), index) for index in range(8)])

    assert set(VersionRegistry(path).versions["process"]) == {str(index) for index in range(8)}
