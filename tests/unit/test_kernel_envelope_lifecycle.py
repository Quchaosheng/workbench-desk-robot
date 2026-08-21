import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libs" / "kernel"))

from workbench.kernel.communication import Message, MessageIntegrityError
from workbench.kernel.lifecycle import LifecycleManager, LifecycleState


def test_message_serialization_retains_type_and_checks_full_envelope() -> None:
    grasp = Message({"target": "red_block"}, "grasp", "1.0.0", "planner")
    place = Message({"target": "red_block"}, "place", "1.0.0", "planner")

    encoded = grasp.to_dict()
    assert encoded["_message_type"] == "grasp"
    assert encoded["_version"] == "1.0.0"
    assert encoded["_actor"] == "planner"
    assert grasp.checksum != place.checksum


def test_message_payload_is_deeply_immutable_and_detached() -> None:
    source = {"target": {"id": "red_block"}, "attempts": [1, 2]}
    message = Message(source, "grasp", "1.0.0", "planner")
    encoded = message.to_dict()

    source["target"]["id"] = "blue_cylinder"
    source["attempts"].append(3)

    assert message.to_dict() == encoded
    with pytest.raises(TypeError):
        message.payload["target"] = {"id": "other"}
    with pytest.raises(TypeError):
        message.payload["target"]["id"] = "other"


def test_message_round_trip_verifies_checksum_and_reserved_fields() -> None:
    encoded = Message({"target": "red_block"}, "grasp", "1.0.0", "planner").to_dict()
    assert Message.from_dict(encoded).to_dict() == encoded

    encoded["target"] = "blue_cylinder"
    with pytest.raises(MessageIntegrityError, match="checksum"):
        Message.from_dict(encoded)

    encoded = Message({"target": "red_block"}, "grasp", "1.0.0", "planner").to_dict()
    encoded["_future"] = "unsupported"
    with pytest.raises(MessageIntegrityError, match="reserved"):
        Message.from_dict(encoded)

    encoded = Message({"target": "red_block"}, "grasp", "1.0.0", "planner").to_dict()
    encoded[1] = "unsupported"
    with pytest.raises(MessageIntegrityError, match="keys must be strings"):
        Message.from_dict(encoded)


def test_message_rejects_non_json_and_non_finite_payloads() -> None:
    with pytest.raises(ValueError, match="finite"):
        Message({"confidence": float("nan")}, "observation", "1.0.0", "perception")
    with pytest.raises(TypeError, match="JSON"):
        Message({"raw": b"bytes"}, "observation", "1.0.0", "perception")


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
