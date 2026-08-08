"""K1-K10 integration test"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from workbench.kernel.communication import Message
from workbench.kernel.event_store import EventStore
from workbench.kernel.lifecycle import LifecycleManager
from workbench.kernel.schema_compiler import SchemaCompiler
from workbench.kernel.startup import SystemBootstrapper


def test_all():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # K1-K2: Schema compiler
        schema_dir = tmp_path / "schemas"
        schema_dir.mkdir()
        (schema_dir / "action.schema.json").write_text(
            json.dumps(
                {
                    "title": "action",
                    "properties": {"id": {"type": "string"}},
                }
            )
        )

        compiler = SchemaCompiler(schema_dir)
        compiler.load_schemas()
        output_dir = tmp_path / "output"
        compiler.compile_all(output_dir / "py", output_dir / "ts")
        print("[PASS] K1-K2 Schema compiler")

        # K4-K5: Communication
        msg = Message(payload={"action": "grasp"}, message_type="action", version="1.0.0", actor="planner")
        assert msg.checksum
        print("[PASS] K4-K5 Communication")

        # K6-K7: Event Store
        log = tmp_path / "events.jsonl"
        store = EventStore(log)
        for i in range(10):
            store.append({"id": i})
        cp = store.create_checkpoint()
        assert cp == 10
        replayed = store.replay(from_checkpoint=0)
        assert len(replayed) == 10
        assert store.verify_integrity()
        print("[PASS] K6-K7 Event Store")

        # K8: Lifecycle
        manager = LifecycleManager()
        manager.create_node("kernel")
        assert manager.startup_sequence()
        states = manager.get_all_states()
        assert states["kernel"] == "active"
        print("[PASS] K8 Lifecycle")

        # K9-K10: Bootstrap
        bootstrapper = SystemBootstrapper(tmp_path / "config")
        assert bootstrapper.bootstrap()
        print("[PASS] K9-K10 Bootstrap")

        print("\n" + "=" * 50)
        print("[SUCCESS] K1-K10 all tests passed")
        print("=" * 50)


if __name__ == "__main__":
    test_all()
