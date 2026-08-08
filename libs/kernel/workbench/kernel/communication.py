"""K4-K5: 通信层和版本检查"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass
class Message:
    payload: dict[str, Any]
    message_type: str
    version: str
    actor: str

    @property
    def checksum(self) -> str:
        envelope = {
            "actor": self.actor,
            "message_type": self.message_type,
            "payload": self.payload,
            "version": self.version,
        }
        content = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.payload,
            "_message_type": self.message_type,
            "_version": self.version,
            "_checksum": self.checksum,
            "_actor": self.actor,
        }


class VersionValidator:
    def __init__(self, compatible_versions):
        self.compatible_versions = compatible_versions

    def validate(self, message: Message) -> bool:
        if message.message_type not in self.compatible_versions:
            return False
        return message.version in self.compatible_versions[message.message_type]


class CommunicationBroker:
    def __init__(self, version_registry):
        self.version_registry = version_registry
        self.message_log = []

    def publish(self, payload, message_type, version, actor):
        msg = Message(payload, message_type, version, actor)
        self.message_log.append(msg)
        return msg
