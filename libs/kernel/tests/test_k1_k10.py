"""K1-K10 integration test"""

import json
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent))

from workbench.kernel.communication import Message
from workbench.kernel.event_store import EventStore
from workbench.kernel.lifecycle import LifecycleManager
from workbench.kernel.schema_compiler import SchemaCompiler, _python_type
from workbench.kernel.startup import SystemBootstrapper
from workbench.kernel.version_registry import VersionRegistry


def test_all():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # K1-K2: Schema compiler
        schema_dir = tmp_path / "schemas"
        schema_dir.mkdir()
        (schema_dir / "action.schema.json").write_text(
            json.dumps(
                {
                    "title": "Action",
                    "type": "object",
                    "required": ["id"],
                    "properties": {
                        "id": {"type": "string"},
                        "retry_count": {"type": "integer"},
                    },
                }
            ),
            encoding="utf-8",
        )

        compiler = SchemaCompiler(schema_dir)
        compiler.load_schemas()
        output_dir = tmp_path / "output"
        compiler.compile_all(output_dir / "py", output_dir / "ts")
        python_model = output_dir / "py" / "action.py"
        typescript_model = output_dir / "ts" / "action.ts"
        namespace = {}
        exec(compile(python_model.read_text(encoding="utf-8"), str(python_model), "exec"), namespace)
        action_model = namespace["Action"]
        assert issubclass(action_model, BaseModel)
        assert action_model(id="act-001").id == "act-001"
        assert action_model.model_fields["id"].is_required()
        assert action_model(id="act-001", retry_count=2).retry_count == 2
        typescript = typescript_model.read_text(encoding="utf-8")
        assert "export interface Action {" in typescript
        assert '"id": string;' in typescript
        assert '"retry_count"?: number;' in typescript
        assert compiler.verify_type_compatibility() == {"action": True}
        print("[PASS] K1-K2 Schema compiler")

        # K4-K5: Communication
        msg = Message(payload={"action": "grasp"}, message_type="action", version="1.0.0", actor="planner")
        assert msg.checksum
        print("[PASS] K4-K5 Communication")

        # K3: Version registry
        registry = VersionRegistry(tmp_path / "versions.json")
        registry.register_schema("action", "1.0.0", {"type": "object"})
        assert VersionRegistry(tmp_path / "versions.json").versions["action"]["1.0.0"]
        print("[PASS] K3 Version registry")

        # K6-K7: Event Store
        log = tmp_path / "events.jsonl"
        store = EventStore(log, legacy_objects=True)
        for i in range(10):
            store.append({"id": i})
        cp = store.create_checkpoint()
        assert cp == 10
        replayed = store.replay(from_checkpoint=0)
        assert len(replayed) == 10
        assert store.verify_integrity()
        reopened = EventStore(log, legacy_objects=True)
        reopened.append({"id": 10})
        restart_checkpoint = reopened.create_checkpoint()
        assert restart_checkpoint == 11
        assert reopened.replay(from_checkpoint=restart_checkpoint) == []
        print("[PASS] K6-K7 Event Store")

        # K8: Lifecycle
        manager = LifecycleManager()
        manager.create_node("kernel")
        assert manager.startup_sequence()
        states = manager.get_all_states()
        assert states["kernel"] == "active"
        assert manager.nodes["kernel"].deactivate()
        assert manager.nodes["kernel"].finalize()
        assert manager.get_all_states()["kernel"] == "finalized"
        print("[PASS] K8 Lifecycle")

        # K9-K10: Bootstrap
        bootstrapper = SystemBootstrapper(tmp_path / "config")
        assert bootstrapper.bootstrap()
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "bootstrap.json").write_text(
            json.dumps(
                {
                    "schemas": ["action"],
                    "nodes": ["kernel"],
                    "version": "1.0.0",
                    "checks": {"event_store_ready": False},
                }
            ),
            encoding="utf-8",
        )
        assert not SystemBootstrapper(tmp_path / "config").bootstrap()
        print("[PASS] K9-K10 Bootstrap")

        print("\n" + "=" * 50)
        print("[SUCCESS] K1-K10 all tests passed")
        print("=" * 50)


if __name__ == "__main__":
    test_all()


# ============================================================================
# 基于真实公开 API 的补充测试
# ============================================================================


def test_schema_compiler_all_types():
    """K1-K2: 所有基础Schema类型"""
    tests = [
        ({"type": "string"}, "str"),
        ({"type": "integer"}, "int"),
        ({"type": "number"}, "float"),
        ({"type": "boolean"}, "bool"),
    ]
    for schema, expected in tests:
        result = _python_type(schema)
        assert result == expected


def test_schema_compiler_nested():
    """K1-K2: 嵌套对象"""
    schema = {"type": "object", "properties": {"motor": {"type": "object"}}}
    assert _python_type(schema) == "dict[str, Any]"


def test_version_registry_persists_versions():
    """K3: 多版本持久化。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_file = Path(tmpdir) / "registry.json"
        registry = VersionRegistry(registry_file)
        registry.register_schema("motor", "1.0.0", {})
        registry.register_schema("motor", "1.0.1", {})

        reloaded = VersionRegistry(registry_file)
        assert set(reloaded.versions["motor"]) == {"1.0.0", "1.0.1"}


def test_message_serialization():
    """K4-K5: 消息序列化"""
    msg = Message({}, "motor", "1.0.0", "planner")
    serialized = json.dumps(msg.to_dict())
    assert "motor" in serialized


def test_message_checksum_is_deterministic():
    """K4-K5: 相同消息产生相同校验和。"""
    msg1 = Message({}, "test", "1.0.0", "a")
    msg2 = Message({}, "test", "1.0.0", "a")
    assert msg1.checksum == msg2.checksum


def test_event_store_persistence():
    """K6-K7: 事件持久化"""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "test.jsonl"
        store1 = EventStore(log_file, legacy_objects=True)
        store1.append({"data": "test"})

        store2 = EventStore(log_file, legacy_objects=True)
        assert store2.replay() == [{"data": "test"}]


def test_event_store_checkpoint():
    """K6-K7: 事件检查点"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = EventStore(Path(tmpdir) / "test.jsonl", legacy_objects=True)
        for i in range(5):
            store.append({"index": i})

        cp = store.create_checkpoint()
        assert cp == 5

        store.append({"index": 5})
        replayed = store.replay(from_checkpoint=cp)
        assert len(replayed) >= 1


def test_event_store_scale():
    """K6-K7: 大规模事件"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = EventStore(Path(tmpdir) / "large.jsonl", legacy_objects=True)
        for i in range(100):
            store.append({"id": i})
        assert len(store.events) == 100


def test_lifecycle_sequence():
    """K8: 完整生命周期"""
    lm = LifecycleManager()
    node = lm.create_node("motor")
    assert node.configure()
    assert node.activate()
    assert node.deactivate()
    assert node.finalize()


def test_lifecycle_invalid():
    """K8: 无效转移"""
    lm = LifecycleManager()
    result = lm.create_node("motor").activate()
    assert not result


# 性能测试
def test_perf_schema():
    """性能: Schema编译"""
    import time

    start = time.time()
    for _ in range(100):
        _python_type({"type": "string"})
    elapsed = (time.time() - start) / 100 * 1000
    assert elapsed < 10


def test_perf_message():
    """性能: 消息创建"""
    import time

    start = time.time()
    for _ in range(100):
        Message({}, "test", "1.0.0", "actor")
    elapsed = (time.time() - start) / 100 * 1000
    assert elapsed < 5


def test_perf_event():
    """性能: 事件追加"""
    import time

    with tempfile.TemporaryDirectory() as tmpdir:
        store = EventStore(Path(tmpdir) / "perf.jsonl", legacy_objects=True)
        start = time.time()
        for i in range(100):
            store.append({"data": i})
        elapsed = (time.time() - start) / 100 * 1000
        assert elapsed < 10


# 版本化格式与持久化测试
def test_versioned_message_preserves_type():
    """版本化消息保留显式消息类型。"""
    msg = Message({"cmd": "move"}, "motor", "1.0.0", "ctrl")
    assert msg.message_type == "motor"


def test_event_store_replays_existing_object_shape():
    """事件存储可以重放已持久化的对象事件。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = EventStore(Path(tmpdir) / "compat.jsonl", legacy_objects=True)
        for i in range(5):
            store.append({"type": "event", "id": i})

        replayed = store.replay()
        assert len(replayed) == 5


def test_multiple_registered_versions_are_preserved():
    """注册表保留同一 schema 的多个显式版本。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = VersionRegistry(Path(tmpdir) / "registry.json")
        registry.register_schema("config", "1.0.0", {})
        registry.register_schema("config", "1.1.0", {})

        assert set(registry.versions["config"]) == {"1.0.0", "1.1.0"}
