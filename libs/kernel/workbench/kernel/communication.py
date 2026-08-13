"""K4-K5: 通信层和版本检查"""

import hashlib
import hmac
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .schema_compiler import SchemaValidationError, validate_schema_instance


class MessageIntegrityError(ValueError):
    """Raised when a serialized message envelope cannot be trusted."""


class BrokerValidationError(ValueError):
    """Raised when a message cannot cross the broker publication boundary."""


def _freeze_json(value: Any, ancestors: set[int] | None = None) -> Any:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("message payload floats must be finite")
        return value
    if isinstance(value, bytes | bytearray):
        raise TypeError("message payload must contain JSON values")

    active = set() if ancestors is None else ancestors
    identity = id(value)
    if identity in active:
        raise TypeError("message payload must not contain recursive containers")
    active.add(identity)
    try:
        if isinstance(value, Mapping):
            frozen: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError("message payload keys must be strings")
                frozen[key] = _freeze_json(item, active)
            return MappingProxyType(frozen)
        if isinstance(value, Sequence) and not isinstance(value, str):
            return tuple(_freeze_json(item, active) for item in value)
    finally:
        active.remove(identity)
    raise TypeError(f"unsupported message payload type: {type(value).__name__}")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class Message:
    payload: Mapping[str, Any]
    message_type: str
    version: str
    actor: str
    _checksum: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.payload, Mapping):
            raise TypeError("message payload must be an object")
        reserved = [key for key in self.payload if isinstance(key, str) and key.startswith("_")]
        if reserved:
            raise ValueError(f"message payload contains reserved fields: {sorted(reserved)}")
        object.__setattr__(self, "payload", _freeze_json(self.payload))
        object.__setattr__(self, "message_type", _require_text(self.message_type, "message_type"))
        object.__setattr__(self, "version", _require_text(self.version, "version"))
        object.__setattr__(self, "actor", _require_text(self.actor, "actor"))
        object.__setattr__(self, "_checksum", self._compute_checksum())

    def _compute_checksum(self) -> str:
        envelope = self._envelope()
        content = json.dumps(
            envelope,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def _envelope(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "message_type": self.message_type,
            "payload": _thaw_json(self.payload),
            "version": self.version,
        }

    @property
    def checksum(self) -> str:
        return self._checksum

    def to_dict(self) -> dict[str, Any]:
        return {
            **_thaw_json(self.payload),
            "_message_type": self.message_type,
            "_version": self.version,
            "_checksum": self.checksum,
            "_actor": self.actor,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Message":
        if not isinstance(value, Mapping):
            raise MessageIntegrityError("serialized message must be an object")
        required = {"_message_type", "_version", "_checksum", "_actor"}
        missing = required - set(value)
        if missing:
            raise MessageIntegrityError(f"serialized message is missing fields: {sorted(missing)}")
        unknown_reserved = {key for key in value if key.startswith("_") and key not in required}
        if unknown_reserved:
            raise MessageIntegrityError(f"serialized message has unknown reserved fields: {sorted(unknown_reserved)}")
        checksum = value["_checksum"]
        if not isinstance(checksum, str) or not checksum:
            raise MessageIntegrityError("serialized message checksum must be a non-empty string")
        payload = {key: item for key, item in value.items() if key not in required}
        try:
            message = cls(payload, value["_message_type"], value["_version"], value["_actor"])
        except (TypeError, ValueError) as exc:
            raise MessageIntegrityError(f"serialized message is invalid: {exc}") from exc
        if not hmac.compare_digest(message.checksum, checksum):
            raise MessageIntegrityError("serialized message checksum does not match its envelope")
        return message


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
        self.message_log: list[Message] = []

    def publish(self, payload, message_type, version, actor):
        try:
            message = Message(payload, message_type, version, actor)
        except (TypeError, ValueError) as exc:
            raise BrokerValidationError(f"invalid message envelope: {exc}") from exc
        versions = self.version_registry.versions.get(message.message_type)
        if not isinstance(versions, dict):
            raise BrokerValidationError(f"message type {message.message_type!r} is not registered")
        schema = versions.get(message.version)
        if not isinstance(schema, dict):
            raise BrokerValidationError(
                f"message version {message.version!r} is not registered for type {message.message_type!r}"
            )
        try:
            validate_schema_instance(_thaw_json(message.payload), schema)
        except SchemaValidationError as exc:
            raise BrokerValidationError(f"message payload does not satisfy the registered schema: {exc}") from exc
        self.message_log.append(message)
        return message
