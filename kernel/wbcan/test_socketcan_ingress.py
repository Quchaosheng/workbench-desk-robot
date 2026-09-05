#!/usr/bin/env python3
"""Exercise the bounded SocketCAN ingress boundary on a virtual CAN device.

The probe deliberately uses two ordinary AF_CAN/CAN_RAW sockets: the adapter
under test and a peer that represents a virtual MCU.  It verifies the exact
read-only projection produced by ``SafeCANBus`` and never treats this virtual
loopback as physical CAN, MCU, actuator, or real-time evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import select
import socket
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
HARDWARE_LIB = ROOT / "libs" / "hardware"
if str(HARDWARE_LIB) not in sys.path:
    sys.path.insert(0, str(HARDWARE_LIB))

from workbench.hardware import (
    CAN_SFF_MASK,
    MCU_CAN_ID_ACK,
    MCU_CAN_ID_COMMAND,
    MCU_CAN_ID_STOP,
    MCU_CAN_ID_STOP_ACK,
    MCU_CAN_ID_TELEMETRY,
    CanExternalRecord,
    CanFrame,
    CanFrameKind,
    CanLinkState,
    CanReceiveStatus,
    CanTransportConfig,
    SafeCANBus,
    SocketCANFilter,
    SocketCANTransport,
    pack_socketcan_frame,
)
from workbench.hardware.socketcan_transport import CAN_FRAME_STRUCT

SCHEMA_VERSION = "socketcan-ingress-report-v1"
RESULTS = frozenset({"PASS", "FAIL", "NOT_EXECUTED"})
EXIT_NOT_EXECUTED = 77
WIRE_VERSION = 0x10
WIRE_MOVE = 1
WIRE_STOP = 5
RECORD_NAMES = frozenset({"ack", "telemetry", "stop_ack", "duplicate", "invalid"})
KERNEL_CONFIG_HASH = re.compile(r"^[0-9a-f]{64}$")
COMMON_REPORT_FIELDS = frozenset(
    {
        "schema_version",
        "scope",
        "result",
        "interface",
        "source",
        "virtual_device",
        "transport",
        "kernel",
        "kernel_config_sha256",
        "timestamp_contract",
        "physical_can",
        "mcu",
        "actuator",
        "hard_real_time",
    }
)
EXTERNAL_RECORD_FIELDS = frozenset(
    {
        "status",
        "source",
        "interface",
        "ingress_sequence",
        "health",
        "frame_valid",
        "exposure_allowed",
        "event_type",
        "frame_kind",
        "arbitration_id",
        "raw_can_id",
        "dlc",
        "data_hex",
        "is_extended_id",
        "is_remote_frame",
        "is_error_frame",
        "monotonic_ts",
        "wall_ts",
        "kernel_timestamp_ns",
        "kernel_drop_count",
        "timestamp_source",
        "reason",
        "callback_errors",
        "confirmed",
        "command_id",
        "sequence_no",
        "opcode",
        "retry_count",
        "result_code",
        "fault_code",
        "device_mode",
        "evidence_refs",
    }
)


class NotExecutedError(RuntimeError):
    """The host lacks a prerequisite for the privileged virtual probe."""


class ProbeFailure(RuntimeError):
    """A probe assertion failed while retaining its partial evidence."""

    def __init__(self, message: str, details: dict[str, Any]) -> None:
        super().__init__(message)
        self.details = details


def _kernel_config_sha256() -> str:
    candidates = (Path("/proc/config.gz"), Path(f"/boot/config-{platform.release()}"))
    for candidate in candidates:
        try:
            return hashlib.sha256(candidate.read_bytes()).hexdigest()
        except OSError:
            continue
    return "unavailable"


def _base_report(interface: str, source: str, *, result: str = "NOT_EXECUTED") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "virtual-socketcan-ingress",
        "result": result,
        "interface": interface,
        "source": source,
        "virtual_device": _virtual_device_name(interface),
        "transport": "AF_CAN/CAN_RAW",
        "kernel": platform.release(),
        "kernel_config_sha256": _kernel_config_sha256(),
        "timestamp_contract": "SO_TIMESTAMPNS plus host monotonic and wall clocks",
        "physical_can": "NOT_EXECUTED",
        "mcu": "NOT_EXECUTED",
        "actuator": "NOT_EXECUTED",
        "hard_real_time": "NOT_EXECUTED",
    }


def _not_executed_report(interface: str, source: str, reason: str) -> dict[str, Any]:
    report = _base_report(interface, source)
    report["reason"] = reason
    return report


def _virtual_device_name(interface: str) -> str:
    if interface.startswith("wbcan"):
        return "wbcan"
    if interface.startswith("vcan"):
        return "vcan"
    return "other-virtual"


def _require_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a bool")
    return value


def _validate_kernel_config_hash(value: object, *, require_digest: bool) -> None:
    digest = _require_string(value, "SocketCAN ingress report kernel_config_sha256")
    if digest == "unavailable":
        if require_digest:
            raise ValueError("PASS report requires a 64-character kernel_config_sha256 digest")
        return
    if KERNEL_CONFIG_HASH.fullmatch(digest) is None:
        raise ValueError("kernel_config_sha256 must be a lowercase SHA-256 digest or unavailable")


def _validate_record_dict(
    record: object,
    *,
    name: str,
    source: str,
    interface: str,
    expected_status: str,
    frame_valid: bool,
    exposed: bool,
    require_deterministic: bool,
) -> None:
    if not isinstance(record, dict):
        raise ValueError(f"{name} record must be an object")
    missing = EXTERNAL_RECORD_FIELDS - record.keys()
    unexpected = record.keys() - EXTERNAL_RECORD_FIELDS
    if missing:
        raise ValueError(f"{name} record is missing fields: {sorted(missing)}")
    if unexpected:
        raise ValueError(f"{name} record contains unexpected fields: {sorted(unexpected)}")
    if record["status"] != expected_status:
        raise ValueError(f"{name} record status is not {expected_status}")
    if record["source"] != source or record["interface"] != interface:
        raise ValueError(f"{name} record source/interface does not match the probe")
    _require_string(record["source"], f"{name}.source")
    _require_string(record["interface"], f"{name}.interface")
    if not isinstance(record["ingress_sequence"], int) or isinstance(record["ingress_sequence"], bool):
        raise ValueError(f"{name}.ingress_sequence must be an integer")
    if record["ingress_sequence"] < 0:
        raise ValueError(f"{name}.ingress_sequence must be non-negative")
    if record["health"] not in {state.value for state in CanLinkState}:
        raise ValueError(f"{name}.health is not a CanLinkState value")
    if record["frame_valid"] is not frame_valid:
        raise ValueError(f"{name}.frame_valid does not match the expected validation result")
    if record["exposure_allowed"] is not exposed:
        raise ValueError(f"{name}.exposure_allowed does not match the expected projection policy")
    _require_bool(record["frame_valid"], f"{name}.frame_valid")
    _require_bool(record["exposure_allowed"], f"{name}.exposure_allowed")
    _require_bool(record["confirmed"], f"{name}.confirmed")
    if type(record["callback_errors"]) is not int or record["callback_errors"] < 0:
        raise ValueError(f"{name}.callback_errors must be a non-negative integer")
    if require_deterministic and record["callback_errors"] != 0:
        raise ValueError(f"{name}.callback_errors must be zero in the deterministic probe")
    if (record["reason"] is None) != (expected_status == "accepted"):
        raise ValueError(f"{name}.reason does not match the accepted/rejected status")
    if record["reason"] is not None:
        _require_string(record["reason"], f"{name}.reason")
    if not isinstance(record["evidence_refs"], list) or len(record["evidence_refs"]) != 1:
        raise ValueError(f"{name}.evidence_refs must contain exactly one reference")
    reference = _require_string(record["evidence_refs"][0], f"{name}.evidence_refs[0]")
    expected_reference = (
        f"can-ingress://{quote(source, safe='')}/{quote(interface, safe='')}/{record['ingress_sequence']}"
    )
    if reference != expected_reference:
        raise ValueError(f"{name}.evidence_refs does not identify the exact ingress sequence")
    arbitration_id = record["arbitration_id"]
    raw_can_id = record["raw_can_id"]
    maximum_arbitration_id = CAN_SFF_MASK if frame_valid else 0xFFFFFFFF
    if arbitration_id is not None and (
        type(arbitration_id) is not int or not 0 <= arbitration_id <= maximum_arbitration_id
    ):
        raise ValueError(f"{name}.arbitration_id is outside the bounded CAN ID range")
    if raw_can_id is not None and (type(raw_can_id) is not int or not 0 <= raw_can_id <= 0xFFFFFFFF):
        raise ValueError(f"{name}.raw_can_id must be a 32-bit unsigned integer when present")
    for flag in ("is_extended_id", "is_remote_frame", "is_error_frame"):
        if record[flag] is not None and type(record[flag]) is not bool:
            raise ValueError(f"{name}.{flag} must be a bool or null")
    if frame_valid and (
        type(arbitration_id) is not int
        or type(raw_can_id) is not int
        or any(record[flag] is not False for flag in ("is_extended_id", "is_remote_frame", "is_error_frame"))
    ):
        raise ValueError(f"{name} valid Wire V1 record must contain standard non-flagged CAN metadata")
    if (
        raw_can_id is not None
        and arbitration_id is not None
        and all(record[flag] is not None for flag in ("is_extended_id", "is_remote_frame", "is_error_frame"))
    ):
        expected_raw_id = arbitration_id
        if record["is_extended_id"]:
            expected_raw_id |= 0x80000000
        if record["is_remote_frame"]:
            expected_raw_id |= 0x40000000
        if record["is_error_frame"]:
            expected_raw_id |= 0x20000000
        if raw_can_id != expected_raw_id:
            raise ValueError(f"{name}.raw_can_id does not match the frame flags")
    if frame_valid:
        if record["dlc"] != 8 or not isinstance(record["data_hex"], str) or len(record["data_hex"]) != 16:
            raise ValueError(f"{name} record must contain a complete eight-byte Wire V1 frame")
        try:
            decoded_data = bytes.fromhex(record["data_hex"])
        except ValueError as exc:
            raise ValueError(f"{name}.data_hex is not hexadecimal") from exc
        if decoded_data.hex() != record["data_hex"]:
            raise ValueError(f"{name}.data_hex must use lowercase hexadecimal")
    else:
        if record["data_hex"] is not None or (
            record["dlc"] is not None and (type(record["dlc"]) is not int or not 0 <= record["dlc"] <= 8)
        ):
            raise ValueError(f"{name} invalid record must retain only bounded raw metadata")
        if any(
            record[field] is not None
            for field in (
                "event_type",
                "frame_kind",
                "command_id",
                "sequence_no",
                "opcode",
                "retry_count",
                "result_code",
                "fault_code",
                "device_mode",
            )
        ):
            raise ValueError(f"{name} invalid record must not contain decoded protocol fields")
    if record["kernel_timestamp_ns"] is not None and (
        type(record["kernel_timestamp_ns"]) is not int or record["kernel_timestamp_ns"] < 0
    ):
        raise ValueError(f"{name}.kernel_timestamp_ns is invalid")
    if frame_valid and record["kernel_timestamp_ns"] is None:
        raise ValueError(f"{name}.kernel_timestamp_ns is required for a valid SocketCAN record")
    if record["timestamp_source"] not in {"kernel", "kernel+host"}:
        if not (not frame_valid and record["timestamp_source"] in {"none", "adapter", "host"}):
            raise ValueError(f"{name}.timestamp_source must describe the available timestamp source")
    for field in ("monotonic_ts", "wall_ts"):
        value = record[field]
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value)
        ):
            raise ValueError(f"{name}.{field} must be finite when present")
        if frame_valid and value is None:
            raise ValueError(f"{name}.{field} is required for a valid SocketCAN record")
    drop_count = record["kernel_drop_count"]
    if drop_count is not None and (type(drop_count) is not int or not 0 <= drop_count <= 0xFFFFFFFF):
        raise ValueError(f"{name}.kernel_drop_count is invalid")


def _validate_checks(checks: object, *, require_all_pass: bool) -> None:
    if not isinstance(checks, list) or not checks:
        raise ValueError("SocketCAN ingress report requires executed checks")
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            raise ValueError(f"check {index} must be an object")
        if set(check) - {"name", "result", "detail"}:
            raise ValueError(f"check {index} contains unexpected fields")
        _require_string(check.get("name"), f"check {index}.name")
        if check.get("result") not in {"PASS", "FAIL"}:
            raise ValueError(f"check {index} has an invalid result")
        if check["result"] == "FAIL":
            _require_string(check.get("detail"), f"check {index}.detail")
    if require_all_pass and any(check["result"] != "PASS" for check in checks):
        raise ValueError("PASS report cannot contain a failed check")
    if not require_all_pass and not any(check["result"] == "FAIL" for check in checks):
        raise ValueError("FAIL report requires a failed check")


def _validate_cleanup(cleanup: object, *, require_clean: bool) -> None:
    if not isinstance(cleanup, dict):
        raise ValueError("SocketCAN ingress report requires cleanup details")
    expected_fields = {"socket_open", "peer_closed", "worker_alive", "external_depth"}
    if set(cleanup) != expected_fields:
        raise ValueError("SocketCAN ingress cleanup fields are incomplete")
    for name in ("socket_open", "peer_closed", "worker_alive"):
        value = cleanup[name]
        if value is not None and type(value) is not bool:
            raise ValueError(f"cleanup.{name} must be bool or null")
    depth = cleanup["external_depth"]
    if depth is not None and (type(depth) is not int or depth < 0):
        raise ValueError("cleanup.external_depth must be a non-negative integer or null")
    if require_clean and (
        cleanup["socket_open"] is not False
        or cleanup["peer_closed"] is not True
        or cleanup["worker_alive"] is not False
        or cleanup["external_depth"] != 0
    ):
        raise ValueError("PASS report requires complete SocketCAN cleanup")


def _validate_records(
    records: object,
    *,
    source: str,
    interface: str,
    require_all: bool,
) -> None:
    if not isinstance(records, dict):
        raise ValueError("SocketCAN ingress report records must be an object")
    unknown = records.keys() - RECORD_NAMES
    if unknown:
        raise ValueError(f"SocketCAN ingress report contains unknown records: {sorted(unknown)}")
    if require_all and set(records) != RECORD_NAMES:
        raise ValueError("PASS report requires all ingress record projections")
    expected = {
        "ack": ("accepted", True, True),
        "telemetry": ("accepted", True, True),
        "stop_ack": ("accepted", True, True),
        "duplicate": ("duplicate", True, False),
        "invalid": ("invalid_frame", False, False),
    }
    for name, record in records.items():
        expected_status, frame_valid, exposed = expected[name]
        _validate_record_dict(
            record,
            name=name,
            source=source,
            interface=interface,
            expected_status=expected_status,
            frame_valid=frame_valid,
            exposed=exposed,
            require_deterministic=require_all,
        )
    if require_all:
        if records["ack"]["frame_kind"] != "ack" or records["ack"]["event_type"] != "action_result":
            raise ValueError("ACK record has the wrong event mapping")
        if records["telemetry"]["frame_kind"] != "telemetry" or records["telemetry"]["event_type"] != "telemetry":
            raise ValueError("telemetry record has the wrong event mapping")
        if records["stop_ack"]["frame_kind"] != "stop_ack" or records["stop_ack"]["event_type"] != "action_result":
            raise ValueError("STOP_ACK record has the wrong event mapping")
        if records["duplicate"]["frame_kind"] != "ack" or records["invalid"]["frame_kind"] is not None:
            raise ValueError("rejection record frame kinds are inconsistent")
        _validate_deterministic_records(records)


def _validate_deterministic_records(records: dict[str, Any]) -> None:
    """Validate the exact five-frame sequence emitted by the virtual probe."""

    expected_sequences = {
        "ack": 0,
        "duplicate": 1,
        "telemetry": 2,
        "invalid": 3,
        "stop_ack": 4,
    }
    for name, sequence in expected_sequences.items():
        if records[name]["ingress_sequence"] != sequence:
            raise ValueError(f"{name} record has an unexpected ingress sequence")

    expected_frames = {
        "ack": {
            "arbitration_id": MCU_CAN_ID_ACK,
            "raw_can_id": MCU_CAN_ID_ACK,
            "data_hex": "1001230100000001",
            "command_id": 0x0123,
            "sequence_no": None,
            "opcode": WIRE_MOVE,
            "retry_count": 0,
            "result_code": 0,
            "fault_code": 0,
            "device_mode": 1,
            "confirmed": True,
            "health": CanLinkState.ACTIVE.value,
        },
        "duplicate": {
            "arbitration_id": MCU_CAN_ID_ACK,
            "raw_can_id": MCU_CAN_ID_ACK,
            "data_hex": "1001230100000001",
            "command_id": 0x0123,
            "sequence_no": None,
            "opcode": WIRE_MOVE,
            "retry_count": 0,
            "result_code": 0,
            "fault_code": 0,
            "device_mode": 1,
            "confirmed": False,
            "health": CanLinkState.ACTIVE.value,
        },
        "telemetry": {
            "arbitration_id": MCU_CAN_ID_TELEMETRY,
            "raw_can_id": MCU_CAN_ID_TELEMETRY,
            "data_hex": "1001020304000000",
            "command_id": None,
            "sequence_no": 0x01020304,
            "opcode": None,
            "retry_count": None,
            "result_code": None,
            "fault_code": 0,
            "device_mode": 0,
            "confirmed": False,
            "health": CanLinkState.ACTIVE.value,
        },
        "invalid": {
            "arbitration_id": MCU_CAN_ID_ACK,
            "raw_can_id": MCU_CAN_ID_ACK,
            "data_hex": None,
            "command_id": None,
            "sequence_no": None,
            "opcode": None,
            "retry_count": None,
            "result_code": None,
            "fault_code": None,
            "device_mode": None,
            "confirmed": False,
            "health": CanLinkState.ACTIVE.value,
        },
        "stop_ack": {
            "arbitration_id": MCU_CAN_ID_STOP_ACK,
            "raw_can_id": MCU_CAN_ID_STOP_ACK,
            "data_hex": "1081230500000003",
            "command_id": 0x8123,
            "sequence_no": None,
            "opcode": WIRE_STOP,
            "retry_count": 0,
            "result_code": 0,
            "fault_code": 0,
            "device_mode": 3,
            "confirmed": True,
            "health": CanLinkState.SAFE_STOPPED.value,
        },
    }
    for name, expected in expected_frames.items():
        record = records[name]
        for field, value in expected.items():
            if record[field] != value:
                raise ValueError(f"{name}.{field} does not match the deterministic Wire V1 probe")
    if records["ack"]["dlc"] != 8 or records["duplicate"]["dlc"] != 8 or records["telemetry"]["dlc"] != 8:
        raise ValueError("accepted and duplicate records must retain DLC 8")
    if records["stop_ack"]["dlc"] != 8 or records["invalid"]["dlc"] != 7:
        raise ValueError("STOP_ACK or invalid record has an unexpected DLC")


def validate_report(report: object, *, require_pass: bool = False) -> None:
    if not isinstance(report, dict):
        raise ValueError("SocketCAN ingress report must be an object")
    if report.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("SocketCAN ingress report schema_version is invalid")
    if report.get("scope") != "virtual-socketcan-ingress":
        raise ValueError("SocketCAN ingress report scope must remain virtual")
    result = report.get("result")
    if result not in RESULTS:
        raise ValueError("SocketCAN ingress report result is invalid")
    expected_fields = set(COMMON_REPORT_FIELDS)
    if result == "NOT_EXECUTED":
        expected_fields.add("reason")
    else:
        expected_fields.update({"checks", "records", "cleanup"})
        if result == "FAIL":
            expected_fields.add("error")
    missing = expected_fields - report.keys()
    unexpected = report.keys() - expected_fields
    if missing:
        raise ValueError(f"SocketCAN ingress report is missing fields: {sorted(missing)}")
    if unexpected:
        raise ValueError(f"SocketCAN ingress report contains unexpected fields: {sorted(unexpected)}")
    for name in ("interface", "source", "transport", "kernel", "timestamp_contract", "kernel_config_sha256"):
        _require_string(report.get(name), f"SocketCAN ingress report {name}")
    _validate_kernel_config_hash(report["kernel_config_sha256"], require_digest=result == "PASS")
    virtual_device = report.get("virtual_device")
    if virtual_device not in {"wbcan", "vcan", "other-virtual"}:
        raise ValueError("SocketCAN ingress report virtual_device is invalid")
    if report["interface"].startswith("wbcan") and virtual_device != "wbcan":
        raise ValueError("wbcan interface must report virtual_device=wbcan")
    if report["interface"].startswith("vcan") and virtual_device != "vcan":
        raise ValueError("vcan interface must report virtual_device=vcan")
    for name in ("physical_can", "mcu", "actuator", "hard_real_time"):
        if report.get(name) != "NOT_EXECUTED":
            raise ValueError(f"SocketCAN ingress report must keep {name} NOT_EXECUTED")
    if result == "NOT_EXECUTED":
        if not isinstance(report.get("reason"), str) or not report["reason"].strip():
            raise ValueError("NOT_EXECUTED report requires a reason")
    elif result == "FAIL":
        if not isinstance(report.get("error"), str) or not report["error"].strip():
            raise ValueError("FAIL report requires an error")
        _validate_checks(report.get("checks"), require_all_pass=False)
        _validate_cleanup(report.get("cleanup"), require_clean=False)
        _validate_records(
            report.get("records"),
            source=report["source"],
            interface=report["interface"],
            require_all=False,
        )
    else:
        _validate_checks(report.get("checks"), require_all_pass=True)
        _validate_cleanup(report.get("cleanup"), require_clean=True)
        _validate_records(
            report.get("records"),
            source=report["source"],
            interface=report["interface"],
            require_all=True,
        )
    if require_pass and result != "PASS":
        raise ValueError(f"required PASS, got {result}")


def write_report(path: Path, report: dict[str, Any]) -> None:
    validate_report(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _ensure_failure_check(checks: list[dict[str, str]], failure: Exception) -> None:
    """Make direct helper/cleanup exceptions visible to the report validator."""

    if any(item.get("result") == "FAIL" for item in checks):
        return
    detail = str(failure).strip() or type(failure).__name__
    checks.append({"name": "probe execution", "result": "FAIL", "detail": detail})


def _require_prerequisites(interface: str) -> None:
    if os.geteuid() != 0:
        raise NotExecutedError("root is required to exercise the virtual SocketCAN interface")
    if not hasattr(socket, "AF_CAN") or not hasattr(socket, "CAN_RAW"):
        raise NotExecutedError("the host Python/kernel does not expose AF_CAN/CAN_RAW")
    if _kernel_config_sha256() == "unavailable":
        raise NotExecutedError("the running kernel configuration is unavailable")
    try:
        socket.if_nametoindex(interface)
    except OSError as exc:
        raise NotExecutedError(f"SocketCAN interface {interface!r} is unavailable: {exc}") from exc
    sysfs_path = Path("/sys/class/net") / interface
    if not sysfs_path.exists():
        raise NotExecutedError(f"SocketCAN interface {interface!r} has no sysfs entry")
    try:
        link_type = (sysfs_path / "type").read_text(encoding="ascii").strip()
    except OSError as exc:
        raise NotExecutedError(f"could not inspect SocketCAN interface {interface!r}: {exc}") from exc
    if link_type != "280":
        raise NotExecutedError(f"interface {interface!r} is not a CAN netdevice")
    if (sysfs_path / "device").exists():
        raise NotExecutedError("this probe is limited to virtual CAN and will not inspect a physical device")


def _wire_frame(arbitration_id: int, payload: bytes, *, dlc: int | None = None) -> CanFrame:
    return CanFrame(
        arbitration_id=arbitration_id,
        data=payload,
        dlc=len(payload) if dlc is None else dlc,
        raw_can_id=arbitration_id,
    )


def _command(command_id: int) -> CanFrame:
    return _wire_frame(
        MCU_CAN_ID_COMMAND,
        bytes([WIRE_VERSION, command_id >> 8, command_id & 0xFF, WIRE_MOVE, 0, 0, 0, 0]),
    )


def _ack(command_id: int) -> CanFrame:
    return _wire_frame(
        MCU_CAN_ID_ACK,
        bytes([WIRE_VERSION, command_id >> 8, command_id & 0xFF, WIRE_MOVE, 0, 0, 0, 1]),
    )


def _stop(command_id: int) -> CanFrame:
    return _wire_frame(
        MCU_CAN_ID_STOP,
        bytes([WIRE_VERSION, command_id >> 8, command_id & 0xFF, WIRE_STOP, 0, 0, 0, 0]),
    )


def _stop_ack(command_id: int) -> CanFrame:
    return _wire_frame(
        MCU_CAN_ID_STOP_ACK,
        bytes([WIRE_VERSION, command_id >> 8, command_id & 0xFF, WIRE_STOP, 0, 0, 0, 3]),
    )


def _telemetry(sequence_no: int) -> CanFrame:
    return _wire_frame(
        MCU_CAN_ID_TELEMETRY,
        bytes([WIRE_VERSION, *sequence_no.to_bytes(4, "big"), 0, 0, 0]),
    )


def _receive_peer_frame(peer: socket.socket, timeout_s: float) -> CanFrame:
    ready, _, _ = select.select([peer], [], [], timeout_s)
    if not ready:
        raise AssertionError("virtual MCU peer did not observe the dispatched command")
    raw = peer.recv(CAN_FRAME_STRUCT.size)
    if len(raw) != CAN_FRAME_STRUCT.size:
        raise AssertionError(f"peer received a short CAN frame: {len(raw)} bytes")
    raw_id, dlc, data = CAN_FRAME_STRUCT.unpack(raw)
    if dlc > 8:
        raise AssertionError(f"peer received an invalid DLC: {dlc}")
    return CanFrame(
        arbitration_id=raw_id & CAN_SFF_MASK,
        data=bytes(data[:dlc]),
        dlc=dlc,
        raw_can_id=raw_id,
    )


def _wait_for_result(bus: SafeCANBus, expected: CanReceiveStatus, timeout_s: float) -> Any:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = bus.service_once(receive_timeout_s=min(0.020, max(0.0, deadline - time.monotonic())))
        if result is not None:
            if result.status is not expected:
                raise AssertionError(f"expected {expected.value}, received {result.status.value}")
            return result
    raise AssertionError(f"did not receive expected {expected.value} result within {timeout_s:.3f}s")


def _record_assertions(record: CanExternalRecord, *, kind: CanFrameKind, event_type: str) -> None:
    if record.status is not CanReceiveStatus.ACCEPTED:
        raise AssertionError(f"record status is {record.status.value}, not accepted")
    if not record.frame_valid or not record.exposure_allowed:
        raise AssertionError("accepted record was not exposed as a valid event")
    if record.frame_kind is not kind or record.event_type != event_type:
        raise AssertionError("external event kind/type does not match the wire frame")
    if record.dlc != 8 or record.kernel_timestamp_ns is None:
        raise AssertionError("external record lost DLC or kernel timestamp metadata")
    if record.timestamp_source not in {"kernel", "kernel+host"}:
        raise AssertionError(f"unexpected timestamp source: {record.timestamp_source}")
    if record.raw_can_id != record.arbitration_id:
        raise AssertionError("external record raw CAN ID does not match standard arbitration ID")
    expected_reference = (
        f"can-ingress://{quote(record.source, safe='')}/{quote(record.interface, safe='')}/{record.ingress_sequence}"
    )
    if record.evidence_refs != (expected_reference,):
        raise AssertionError("external record lacks the exact ingress evidence reference")


def _rejection_assertions(record: CanExternalRecord, *, status: CanReceiveStatus, frame_valid: bool) -> None:
    if record.status is not status:
        raise AssertionError(f"rejection record status is {record.status.value}, not {status.value}")
    if record.frame_valid is not frame_valid or record.exposure_allowed:
        raise AssertionError("rejection record violates the fail-closed exposure policy")
    if record.confirmed or record.evidence_refs == ():
        raise AssertionError("rejection record contains completion or evidence metadata")
    expected_reference = (
        f"can-ingress://{quote(record.source, safe='')}/{quote(record.interface, safe='')}/{record.ingress_sequence}"
    )
    if record.evidence_refs != (expected_reference,):
        raise AssertionError("rejection record lacks the exact ingress evidence reference")


def _consume_external_record(bus: SafeCANBus, record: CanExternalRecord, check: Any, name: str) -> None:
    consumed = bus.take_external_record()
    check(f"{name} projection is consumable through the read-only queue", consumed == record)
    check(f"{name} projection queue is empty after consumption", bus.take_external_record() is None)


def run_probe(interface: str, source: str, timeout_s: float) -> dict[str, Any]:
    _require_prerequisites(interface)
    transport = SocketCANTransport(
        interface,
        source=source,
        filters=(
            SocketCANFilter(MCU_CAN_ID_ACK, CAN_SFF_MASK),
            SocketCANFilter(MCU_CAN_ID_STOP_ACK, CAN_SFF_MASK),
            SocketCANFilter(MCU_CAN_ID_TELEMETRY, CAN_SFF_MASK),
        ),
        receive_own_messages=False,
        loopback=True,
        require_kernel_timestamp=True,
    )
    peer: socket.socket | None = None
    bus: SafeCANBus | None = None
    records: dict[str, dict[str, object | None]] = {}
    checks: list[dict[str, str]] = []
    failure: Exception | None = None
    cleanup: dict[str, object | None] = {
        "socket_open": None,
        "peer_closed": None,
        "worker_alive": None,
        "external_depth": None,
    }

    def check(name: str, condition: bool, detail: str = "") -> None:
        if condition:
            checks.append({"name": name, "result": "PASS"})
            return
        checks.append({"name": name, "result": "FAIL", "detail": detail or name})
        raise AssertionError(detail or name)

    try:
        bus = SafeCANBus(
            transport,
            config=CanTransportConfig(
                source=source,
                interface=interface,
                ack_timeout_s=timeout_s,
                external_capacity=8,
            ),
        )
        check("adapter starts through the unified runtime", bus.start(background=False))
        peer = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        peer.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_LOOPBACK, 1)
        peer.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_RECV_OWN_MSGS, 0)
        peer.bind((interface,))
        peer.setblocking(False)

        command_id = 0x0123
        check("Wire V1 command is admitted", bus.send(_command(command_id)).accepted)
        check("adapter dispatches one command to the virtual peer", bus.service_once() is None)
        dispatched = _receive_peer_frame(peer, timeout_s)
        check(
            "peer observes the expected command arbitration ID and DLC",
            dispatched.arbitration_id == MCU_CAN_ID_COMMAND
            and dispatched.raw_can_id == MCU_CAN_ID_COMMAND
            and dispatched.dlc == 8
            and dispatched.data == _command(command_id).data,
        )

        peer.send(pack_socketcan_frame(_ack(command_id)))
        accepted_ack = _wait_for_result(bus, CanReceiveStatus.ACCEPTED, timeout_s)
        if accepted_ack.external_record is None:
            raise AssertionError("accepted ACK did not produce an external record")
        _record_assertions(accepted_ack.external_record, kind=CanFrameKind.ACK, event_type="action_result")
        check("ACK projection confirms the dispatched command", accepted_ack.external_record.confirmed)
        check(
            "ACK projection preserves command correlation fields",
            accepted_ack.external_record.command_id == command_id
            and accepted_ack.external_record.opcode == WIRE_MOVE
            and accepted_ack.external_record.retry_count == 0
            and accepted_ack.external_record.result_code == 0
            and accepted_ack.external_record.fault_code == 0
            and accepted_ack.external_record.device_mode == 1,
        )
        _consume_external_record(bus, accepted_ack.external_record, check, "ACK")
        records["ack"] = accepted_ack.external_record.to_dict()

        peer.send(pack_socketcan_frame(_ack(command_id)))
        duplicate = _wait_for_result(bus, CanReceiveStatus.DUPLICATE, timeout_s)
        if duplicate.external_record is None:
            raise AssertionError("duplicate ACK did not produce a rejection projection")
        check(
            "duplicate ACK is observable but not externally exposed",
            duplicate.external_record.status is CanReceiveStatus.DUPLICATE
            and not duplicate.external_record.exposure_allowed,
        )
        _rejection_assertions(
            duplicate.external_record,
            status=CanReceiveStatus.DUPLICATE,
            frame_valid=True,
        )
        check("duplicate ACK does not enter the external queue", bus.take_external_record() is None)
        records["duplicate"] = duplicate.external_record.to_dict()

        telemetry_sequence = 0x01020304
        peer.send(pack_socketcan_frame(_telemetry(telemetry_sequence)))
        telemetry_result = _wait_for_result(bus, CanReceiveStatus.ACCEPTED, timeout_s)
        if telemetry_result.external_record is None:
            raise AssertionError("telemetry did not produce an external record")
        _record_assertions(telemetry_result.external_record, kind=CanFrameKind.TELEMETRY, event_type="telemetry")
        check(
            "telemetry projection preserves the Wire V1 sequence",
            telemetry_result.external_record.sequence_no == telemetry_sequence,
        )
        check(
            "telemetry projection preserves health fields",
            telemetry_result.external_record.fault_code == 0
            and telemetry_result.external_record.device_mode == 0
            and not telemetry_result.external_record.confirmed,
        )
        _consume_external_record(bus, telemetry_result.external_record, check, "telemetry")
        records["telemetry"] = telemetry_result.external_record.to_dict()

        malformed = CAN_FRAME_STRUCT.pack(MCU_CAN_ID_ACK, 7, b"\x10\0\x01\x01\0\0\0\x01")
        peer.send(malformed)
        invalid = _wait_for_result(bus, CanReceiveStatus.INVALID_FRAME, timeout_s)
        if invalid.external_record is None:
            raise AssertionError("malformed frame did not produce a rejection projection")
        check(
            "wrong-DLC Wire V1 ingress is rejected and not exposed",
            not invalid.external_record.frame_valid and not invalid.external_record.exposure_allowed,
        )
        _rejection_assertions(
            invalid.external_record,
            status=CanReceiveStatus.INVALID_FRAME,
            frame_valid=False,
        )
        check("wrong-DLC ingress does not enter the external queue", bus.take_external_record() is None)
        records["invalid"] = invalid.external_record.to_dict()

        stop_command_id = 0x8123
        check("Wire V1 STOP is admitted", bus.send(_stop(stop_command_id)).accepted)
        check("adapter dispatches STOP to the virtual peer", bus.service_once() is None)
        dispatched_stop = _receive_peer_frame(peer, timeout_s)
        check(
            "peer observes the expected STOP arbitration ID, opcode and DLC",
            dispatched_stop.arbitration_id == MCU_CAN_ID_STOP
            and dispatched_stop.raw_can_id == MCU_CAN_ID_STOP
            and dispatched_stop.dlc == 8
            and dispatched_stop.data == _stop(stop_command_id).data,
        )
        peer.send(pack_socketcan_frame(_stop_ack(stop_command_id)))
        accepted_stop_ack = _wait_for_result(bus, CanReceiveStatus.ACCEPTED, timeout_s)
        if accepted_stop_ack.external_record is None:
            raise AssertionError("accepted STOP_ACK did not produce an external record")
        _record_assertions(
            accepted_stop_ack.external_record,
            kind=CanFrameKind.STOP_ACK,
            event_type="action_result",
        )
        check(
            "STOP_ACK confirms the safe-stop transition",
            accepted_stop_ack.confirmed
            and accepted_stop_ack.external_record.command_id == stop_command_id
            and accepted_stop_ack.external_record.opcode == WIRE_STOP
            and accepted_stop_ack.external_record.retry_count == 0
            and accepted_stop_ack.external_record.result_code == 0
            and accepted_stop_ack.external_record.fault_code == 0
            and accepted_stop_ack.external_record.device_mode == 3
            and bus.state is CanLinkState.SAFE_STOPPED,
        )
        _consume_external_record(bus, accepted_stop_ack.external_record, check, "STOP_ACK")
        records["stop_ack"] = accepted_stop_ack.external_record.to_dict()

        check(
            "all accepted records carry source and interface identity",
            all(
                record["source"] == source and record["interface"] == interface
                for record in records.values()
                if record.get("status") == "accepted"
            ),
        )
        check(
            "ingress references are monotonic",
            records["ack"]["ingress_sequence"]
            < records["duplicate"]["ingress_sequence"]
            < records["telemetry"]["ingress_sequence"]
            < records["invalid"]["ingress_sequence"]
            < records["stop_ack"]["ingress_sequence"],
        )
    except Exception as exc:  # noqa: BLE001 - retain partial virtual evidence before reporting failure.
        failure = exc
    finally:
        if bus is not None:
            try:
                shutdown_ok = bus.shutdown(timeout_s=max(1.0, timeout_s * 4))
                if not shutdown_ok and failure is None:
                    failure = AssertionError("SafeCANBus shutdown did not complete")
            except Exception as exc:  # noqa: BLE001 - cleanup failure is part of the probe evidence.
                if failure is None:
                    failure = exc
        if peer is not None:
            try:
                peer.close()
            except Exception as exc:  # noqa: BLE001 - retain cleanup failures in the report.
                if failure is None:
                    failure = exc
        if bus is not None:
            try:
                stale_result = bus.service_once()
            except Exception as exc:  # noqa: BLE001 - post-shutdown behavior is evidence.
                stale_result = exc
            try:
                external_records_empty = bus.external_records() == ()
                external_depth = bus.external_depth
            except Exception as exc:  # noqa: BLE001 - retain cleanup inspection failures in the report.
                external_records_empty = False
                external_depth = None
                if failure is None:
                    failure = exc
            try:
                socket_open = transport.is_open
            except Exception as exc:  # noqa: BLE001 - retain cleanup inspection failures in the report.
                socket_open = None
                if failure is None:
                    failure = exc
            try:
                peer_closed = peer is None or peer.fileno() == -1
            except Exception as exc:  # noqa: BLE001 - retain cleanup inspection failures in the report.
                peer_closed = False
                if failure is None:
                    failure = exc
            try:
                worker_alive = bus.runtime.worker_alive
            except Exception as exc:  # noqa: BLE001 - retain cleanup inspection failures in the report.
                worker_alive = None
                if failure is None:
                    failure = exc
            cleanup.update(
                {
                    "socket_open": socket_open,
                    "peer_closed": peer_closed,
                    "worker_alive": worker_alive,
                    "external_depth": external_depth,
                }
            )

            cleanup_checks = (
                ("shutdown clears the external projection", external_records_empty),
                ("shutdown closes the SocketCAN descriptor", socket_open is False),
                ("shutdown closes the peer socket", peer_closed),
                ("shutdown leaves no runtime worker", worker_alive is False),
                ("shutdown rejects a stale post-close service cycle", stale_result is None),
            )
            for name, condition in cleanup_checks:
                check_result: dict[str, str] = {"name": name, "result": "PASS" if condition else "FAIL"}
                if not condition:
                    check_result["detail"] = name
                    if failure is None:
                        failure = AssertionError(name)
                checks.append(check_result)
        elif failure is None:
            failure = AssertionError("probe did not construct a SafeCANBus")

        if failure is not None:
            _ensure_failure_check(checks, failure)

    details = {
        "checks": checks,
        "records": records,
        "cleanup": cleanup,
        "virtual_device": _virtual_device_name(interface),
    }
    if failure is not None:
        raise ProbeFailure(f"{type(failure).__name__}: {failure}", details) from failure
    return details


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("interface", nargs="?", default="wbcan0")
    parser.add_argument("--source", default="virtual-wbcan")
    parser.add_argument("--timeout", type=float, default=0.5)
    parser.add_argument("--report", type=Path, default=Path("/tmp/wbcan-socketcan-ingress-report.json"))
    parser.add_argument("--validate-report", type=Path)
    parser.add_argument("--write-not-executed-report", type=Path)
    parser.add_argument("--not-executed-reason")
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be a finite positive number")
    if args.validate_report is not None:
        try:
            validate_report(
                json.loads(args.validate_report.read_text(encoding="utf-8")), require_pass=args.require_pass
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            parser.error(str(exc))
        print(f"SocketCAN ingress report valid: {args.validate_report}")
        return 0

    if args.write_not_executed_report is not None:
        if not args.not_executed_reason or not args.not_executed_reason.strip():
            parser.error("--not-executed-reason is required with --write-not-executed-report")
        try:
            write_report(
                args.write_not_executed_report,
                _not_executed_report(args.interface, args.source, args.not_executed_reason.strip()),
            )
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        print(f"NOT_EXECUTED report written: {args.write_not_executed_report}")
        return 0

    report = _base_report(args.interface, args.source)
    try:
        report.update(run_probe(args.interface, args.source, args.timeout))
        report["result"] = "PASS"
    except NotExecutedError as exc:
        report["reason"] = str(exc)
        report["result"] = "NOT_EXECUTED"
    except ProbeFailure as exc:
        report.update(exc.details)
        report["error"] = str(exc)
        report["result"] = "FAIL"
    except Exception as exc:  # noqa: BLE001 - preserve deterministic probe failure as evidence.
        report["error"] = f"{type(exc).__name__}: {exc}"
        report.setdefault(
            "checks",
            [{"name": "probe execution", "result": "FAIL", "detail": report["error"]}],
        )
        report.setdefault("records", {})
        report.setdefault(
            "cleanup",
            {"socket_open": None, "peer_closed": None, "worker_alive": None, "external_depth": None},
        )
        report["result"] = "FAIL"
    try:
        write_report(args.report, report)
        validate_report(report, require_pass=args.require_pass)
    except (OSError, ValueError) as exc:
        print(f"FAIL: could not write or validate SocketCAN ingress report: {exc}", file=sys.stderr)
        return 1

    if report["result"] == "PASS":
        print(f"PASS  SocketCAN ingress evidence: {args.report}")
        return 0
    if report["result"] == "NOT_EXECUTED":
        print(f"NOT_EXECUTED  {report['reason']}")
        return 1 if args.require_pass else EXIT_NOT_EXECUTED
    print(f"FAIL  {report['error']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
