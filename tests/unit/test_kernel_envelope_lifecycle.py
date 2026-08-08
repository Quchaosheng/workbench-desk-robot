import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libs" / "kernel"))

from workbench.kernel.communication import Message
from workbench.kernel.lifecycle import LifecycleManager, LifecycleState


def test_message_serialization_retains_type_and_checks_full_envelope() -> None:
    grasp = Message({"target": "red_block"}, "grasp", "1.0.0", "planner")
    place = Message({"target": "red_block"}, "place", "1.0.0", "planner")

    encoded = grasp.to_dict()
    assert encoded["_message_type"] == "grasp"
    assert encoded["_version"] == "1.0.0"
    assert encoded["_actor"] == "planner"
    assert grasp.checksum != place.checksum


def test_lifecycle_supports_shutdown_and_rejects_duplicate_nodes() -> None:
    manager = LifecycleManager()
    node = manager.create_node("kernel")
    with pytest.raises(ValueError, match="node already exists"):
        manager.create_node("kernel")

    assert node.state is LifecycleState.CREATED
    assert node.configure()
    assert node.activate()
    assert node.deactivate()
    assert node.finalize()
    assert not node.activate()
    assert manager.get_all_states() == {"kernel": "finalized"}
