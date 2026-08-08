"""K4-K5: 通信层和版本检查"""
import json
import hashlib
import uuid
from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class Message:
    payload: Dict[str, Any]
    message_type: str
    version: str
    actor: str
    
    @property
    def checksum(self):
        content = json.dumps(self.payload, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def to_dict(self):
        return {
            **self.payload,
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
