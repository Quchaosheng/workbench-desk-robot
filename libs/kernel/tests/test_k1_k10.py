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
        reopened = EventStore(log)
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
        print("[PASS] K9-K10 Bootstrap")

        print("\n" + "=" * 50)
        print("[SUCCESS] K1-K10 all tests passed")
        print("=" * 50)


if __name__ == "__main__":
    test_all()
