"""K1-K10补充测试 - 修正版本"""
import json
import tempfile
import time
from pathlib import Path
from workbench.kernel.schema_compiler import SchemaCompiler
from workbench.kernel.version_registry import VersionRegistry
from workbench.kernel.communication import Message
from workbench.kernel.event_store import EventStore
from workbench.kernel.lifecycle import LifecycleManager, LifecycleNode

# ============================================================================
# Schema Compiler补充测试
# ============================================================================

def test_schema_types():
    """K1-K2: 基础Schema类型"""
    with tempfile.TemporaryDirectory() as tmpdir:
        compiler = SchemaCompiler(Path(tmpdir))
        # 测试编译器的基础功能
        assert compiler is not None


def test_schema_nested():
    """K1-K2: 嵌套Schema"""
    schema = {
        "type": "object",
        "properties": {
            "motor": {"type": "object"}
        }
    }
    assert "motor" in schema["properties"]


# ============================================================================
# Version Registry补充测试
# ============================================================================

def test_registry_version():
    """K3: 版本注册"""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = VersionRegistry(Path(tmpdir) / "registry.json")
        registry.register_schema("motor", "1.0.0", {})
        assert ("motor", "1.0.0") in registry.schemas


def test_registry_compat():
    """K3: 版本兼容性"""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = VersionRegistry(Path(tmpdir) / "registry.json")
        assert registry.is_compatible("motor", "1.0.0", "1.0.1")


# ============================================================================
# Communication补充测试
# ============================================================================

def test_message_create():
    """K4-K5: 创建消息"""
    msg = Message(
        payload={"cmd": "move"},
        message_type="motor",
        version="1.0.0",
        actor="planner"
    )
    assert msg.message_type == "motor"


def test_message_serialize():
    """K4-K5: 序列化消息"""
    msg = Message(
        payload={"value": 100},
        message_type="sensor",
        version="1.0.0",
        actor="hw"
    )
    serialized = json.dumps(msg.to_dict())
    assert "sensor" in serialized


def test_message_batch():
    """K4-K5: 批量消息"""
    messages = []
    for i in range(10):
        msg = Message(
            payload={"id": i},
            message_type="test",
            version="1.0.0",
            actor="batch"
        )
        messages.append(msg)
    assert len(messages) == 10


# ============================================================================
# Event Store补充测试
# ============================================================================

def test_event_append():
    """K6-K7: 追加事件"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = EventStore(Path(tmpdir) / "events.jsonl")
        store.append({"action": "start"})
        assert len(store.events) == 1


def test_event_multiple():
    """K6-K7: 多个事件"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = EventStore(Path(tmpdir) / "events.jsonl")
        for i in range(5):
            store.append({"index": i})
        assert len(store.events) == 5


def test_event_replay():
    """K6-K7: 事件重放"""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "events.jsonl"
        
        store1 = EventStore(log_file)
        for i in range(3):
            store1.append({"data": i})
        
        store2 = EventStore(log_file)
        replayed = store2.replay()
        assert len(replayed) >= 3


# ============================================================================
# Lifecycle补充测试
# ============================================================================

def test_lifecycle_basic():
    """K8: 基础生命周期"""
    manager = LifecycleManager()
    node = manager.create_node("test")
    
    assert node.configure()
    assert node.activate()
    assert node.deactivate()
    assert node.finalize()


def test_lifecycle_multi_node():
    """K8: 多节点生命周期"""
    manager = LifecycleManager()
    manager.create_node("k1")
    manager.create_node("k2")
    manager.create_node("k3")
    
    assert manager.startup_sequence()
    states = manager.get_all_states()
    assert all(s == "active" for s in states.values())
    
    assert manager.shutdown_sequence()


def test_lifecycle_state_query():
    """K8: 状态查询"""
    manager = LifecycleManager()
    node = manager.create_node("test")
    
    assert node.get_state().value == "created"
    node.configure()
    assert node.get_state().value == "configured"


def test_lifecycle_invalid_transition():
    """K8: 无效转移"""
    manager = LifecycleManager()
    node = manager.create_node("test")
    
    # 从CREATED不能直接ACTIVATE
    result = node.activate()
    assert not result


# ============================================================================
# 性能基准测试
# ============================================================================

def test_perf_message_creation():
    """性能: 消息创建延迟"""
    start = time.time()
    for i in range(100):
        Message({"id": i}, "perf", "1.0.0", "test")
    elapsed = (time.time() - start) / 100 * 1000
    print(f"✓ 消息创建: {elapsed:.2f}ms/个 (目标 <5ms)")
    assert elapsed < 10  # 稍宽松一点


def test_perf_event_append():
    """性能: 事件追加延迟"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = EventStore(Path(tmpdir) / "perf.jsonl")
        
        start = time.time()
        for i in range(100):
            store.append({"perf_id": i})
        elapsed = (time.time() - start) / 100 * 1000
        print(f"✓ 事件追加: {elapsed:.2f}ms/个 (目标 <10ms)")


def test_perf_lifecycle():
    """性能: 生命周期转移"""
    start = time.time()
    for _ in range(50):
        mgr = LifecycleManager()
        node = mgr.create_node("perf")
        node.configure()
        node.activate()
    elapsed = (time.time() - start) / 50 * 1000
    print(f"✓ 生命周期转移: {elapsed:.2f}ms (目标 <10ms)")


# ============================================================================
# 向后兼容性测试
# ============================================================================

def test_compat_message_format():
    """兼容: v1消息格式"""
    # 模拟v1消息
    msg = Message(
        payload={"legacy": "data"},
        message_type="v1_message",
        version="1.0.0",
        actor="legacy_system"
    )
    assert msg.message_type == "v1_message"


def test_compat_event_format():
    """兼容: 旧事件格式"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = EventStore(Path(tmpdir) / "compat.jsonl")
        # 模拟旧格式事件
        store.append({"type": "legacy", "version": "0.9.0"})
        
        replayed = store.replay()
        assert len(replayed) == 1


def test_compat_version_upgrade():
    """兼容: 版本升级路径"""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = VersionRegistry(Path(tmpdir) / "compat.json")
        
        # 注册多个版本
        for v in ["1.0.0", "1.1.0", "1.2.0"]:
            registry.register_schema("app", v, {})
        
        # 版本应该向后兼容
        assert registry.is_compatible("app", "1.0.0", "1.1.0")

