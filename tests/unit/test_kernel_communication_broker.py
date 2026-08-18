import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libs" / "kernel"))

from workbench.kernel.communication import BrokerValidationError, CommunicationBroker
from workbench.kernel.version_registry import VersionRegistry

ACTION_SCHEMA = {
    "type": "object",
    "required": ["target", "speed"],
    "additionalProperties": False,
    "properties": {
        "target": {"type": "string", "pattern": "^[a-z_]+$"},
        "speed": {"type": "number", "minimum": 0, "maximum": 1},
    },
}


def broker(tmp_path: Path) -> CommunicationBroker:
    registry = VersionRegistry(tmp_path / "versions.json")
    registry.register_schema("action", "1.0.0", ACTION_SCHEMA)
    return CommunicationBroker(registry)


def test_broker_publishes_only_registered_schema_valid_messages(tmp_path: Path) -> None:
    boundary = broker(tmp_path)
    message = boundary.publish({"target": "red_block", "speed": 0.5}, "action", "1.0.0", "planner")
    assert boundary.message_log == [message]
    assert message.payload["target"] == "red_block"


@pytest.mark.parametrize(
    "message_type, version, error",
    [
        ("unknown", "1.0.0", "type.*not registered"),
        ("action", "2.0.0", "version.*not registered"),
    ],
)
def test_broker_rejects_unknown_type_or_exact_version(
    tmp_path: Path, message_type: str, version: str, error: str
) -> None:
    boundary = broker(tmp_path)
    with pytest.raises(BrokerValidationError, match=error):
        boundary.publish({"target": "red_block", "speed": 0.5}, message_type, version, "planner")
    assert boundary.message_log == []


@pytest.mark.parametrize(
    "payload, error",
    [
        ({"target": "red_block"}, "missing fields"),
        ({"target": "Red Block", "speed": 0.5}, "pattern"),
        ({"target": "red_block", "speed": 2.0}, "maximum"),
        ({"target": "red_block", "speed": 0.5, "raw_joint": 1}, "extra fields"),
        ({"target": "red_block", "speed": True}, "does not match type"),
        ({"_actor": "forged", "target": "red_block", "speed": 0.5}, "reserved"),
    ],
)
def test_broker_rejects_invalid_payload_without_partial_log(tmp_path: Path, payload: dict, error: str) -> None:
    boundary = broker(tmp_path)
    with pytest.raises(BrokerValidationError, match=error):
        boundary.publish(payload, "action", "1.0.0", "planner")
    assert boundary.message_log == []


def test_broker_uses_registry_state_after_reopen(tmp_path: Path) -> None:
    path = tmp_path / "versions.json"
    registry = VersionRegistry(path)
    registry.register_schema("action", "1.0.0", ACTION_SCHEMA)
    reopened = CommunicationBroker(VersionRegistry(path))
    assert reopened.publish({"target": "red_block", "speed": 1}, "action", "1.0.0", "planner")


def test_broker_rejects_registered_content_that_is_not_a_schema(tmp_path: Path) -> None:
    registry = VersionRegistry(tmp_path / "versions.json")
    registry.register_schema("action", "1.0.0", "not-a-schema")
    boundary = CommunicationBroker(registry)
    with pytest.raises(BrokerValidationError, match=r"version.*not registered"):
        boundary.publish({}, "action", "1.0.0", "planner")
    assert boundary.message_log == []
