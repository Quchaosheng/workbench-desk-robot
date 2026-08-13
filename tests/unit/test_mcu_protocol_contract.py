import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from workbench.kernel.schema_compiler import SchemaCompiler
from workbench_contracts import (
    McuDeviceMode,
    McuFaultCode,
    McuFrame,
    McuFrameKind,
    McuOpcode,
    McuStopAckFrame,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "interfaces/json_schema/mcu_protocol.schema.json"
EXAMPLE_PATH = ROOT / "interfaces/examples/mcu-frame-stop-ack.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)
PROTOCOL_DOC = (ROOT / "docs/architecture/mcu-protocol-v1.md").read_text(encoding="utf-8")

COMMON = {
    "protocol_version": "1.0",
    "frame_id": "mcu-frame-test-001",
    "sent_at_us": 19310000,
    "clock_id": "monotonic",
}

VALID_FRAMES = {
    "command lower bound": {
        **COMMON,
        "frame_kind": "command",
        "command_id": 0,
        "opcode": "move",
        "retry_count": 0,
    },
    "command upper bound": {
        **COMMON,
        "frame_kind": "command",
        "command_id": 32767,
        "opcode": "heartbeat",
        "retry_count": 255,
    },
    "successful ack": {
        **COMMON,
        "frame_kind": "ack",
        "command_id": 19,
        "opcode": "hold",
        "result_code": 0,
        "fault_code": "none",
        "device_mode": "holding",
        "retry_count": 1,
    },
    "failed ack": {
        **COMMON,
        "frame_kind": "ack",
        "command_id": 20,
        "opcode": "grip_close",
        "result_code": 1,
        "fault_code": "malformed_frame",
        "device_mode": "faulted",
        "retry_count": 0,
    },
    "healthy telemetry": {
        **COMMON,
        "frame_kind": "telemetry",
        "sequence_no": 4294967295,
        "fault_code": "none",
        "device_mode": "idle",
    },
    "fault telemetry": {
        **COMMON,
        "frame_kind": "telemetry",
        "sequence_no": 0,
        "fault_code": "watchdog_expired",
        "device_mode": "faulted",
    },
    "stop lower bound": {
        **COMMON,
        "frame_kind": "stop",
        "command_id": 32768,
        "opcode": "stop",
        "retry_count": 0,
    },
    "failed stop ack upper bound": {
        **COMMON,
        "frame_kind": "stop_ack",
        "command_id": 65535,
        "opcode": "stop",
        "result_code": 1,
        "fault_code": "stop_rejected",
        "device_mode": "faulted",
        "retry_count": 2,
    },
}


def changed(frame_name: str, **updates: object) -> dict[str, object]:
    payload = deepcopy(VALID_FRAMES[frame_name])
    payload.update(updates)
    return payload


INVALID_FRAMES = {
    "unknown protocol version": changed("command lower bound", protocol_version="1.1"),
    "unknown field": changed("command lower bound", confirmation=True),
    "unknown frame kind": changed("command lower bound", frame_kind="event"),
    "invalid frame id": changed("command lower bound", frame_id="frame-1"),
    "wall clock": changed("command lower bound", clock_id="wall"),
    "timestamp string": changed("command lower bound", sent_at_us="19310000"),
    "negative timestamp": changed("command lower bound", sent_at_us=-1),
    "boolean command id": changed("command lower bound", command_id=True),
    "command in stop id range": changed("command lower bound", command_id=32768),
    "command uses stop opcode": changed("command lower bound", opcode="stop"),
    "command uses reset opcode": changed("command lower bound", opcode="reset"),
    "command carries ack field": changed("command lower bound", result_code=0),
    "retry count overflow": changed("command lower bound", retry_count=256),
    "ack in stop id range": changed("successful ack", command_id=32768),
    "successful ack carries fault": changed("successful ack", fault_code="malformed_frame"),
    "successful ack is faulted": changed("successful ack", device_mode="faulted"),
    "failed ack carries no fault": changed("failed ack", fault_code="none"),
    "failed ack carries transport fault": changed("failed ack", fault_code="link_lost"),
    "invalid result code": changed("successful ack", result_code=2),
    "boolean result code": changed("successful ack", result_code=True),
    "telemetry carries command id": changed("healthy telemetry", command_id=1),
    "healthy telemetry is faulted": changed("healthy telemetry", device_mode="faulted"),
    "fault telemetry remains moving": changed("fault telemetry", device_mode="moving"),
    "telemetry carries host timeout": changed("fault telemetry", fault_code="ack_timeout"),
    "telemetry sequence overflow": changed("healthy telemetry", sequence_no=4294967296),
    "stop in ordinary id range": changed("stop lower bound", command_id=32767),
    "stop uses ordinary opcode": changed("stop lower bound", opcode="hold"),
    "stop ack in ordinary id range": changed("failed stop ack upper bound", command_id=32767),
    "failed stop ack carries no fault": changed("failed stop ack upper bound", fault_code="none"),
    "failed stop ack remains stopped": changed("failed stop ack upper bound", device_mode="stopped"),
}
missing_opcode = deepcopy(VALID_FRAMES["command lower bound"])
missing_opcode.pop("opcode")
INVALID_FRAMES["missing required field"] = missing_opcode


def schema_accepts(payload: dict[str, object]) -> bool:
    return not list(VALIDATOR.iter_errors(payload))


def model_accepts(payload: dict[str, object]) -> bool:
    try:
        McuFrame.model_validate(payload)
    except ValidationError:
        return False
    return True


def classify_ordinary_serial(last_accepted: int, candidate: int) -> str:
    delta = (candidate - last_accepted) % 32768
    if delta == 0:
        return "duplicate"
    if delta < 16384:
        return "newer"
    return "stale_or_ambiguous"


def classify_telemetry_sequence(last_accepted: int, candidate: int) -> str:
    delta = (candidate - last_accepted) % 4294967296
    if delta == 0:
        return "duplicate"
    if delta < 2147483648:
        return "newer"
    return "stale_or_ambiguous"


@pytest.mark.parametrize(("label", "payload"), VALID_FRAMES.items())
def test_schema_and_model_accept_valid_frame_corpus(label: str, payload: dict[str, object]) -> None:
    assert schema_accepts(payload), label
    assert model_accepts(payload), label


@pytest.mark.parametrize(("label", "payload"), INVALID_FRAMES.items())
def test_schema_and_model_reject_invalid_frame_corpus(label: str, payload: dict[str, object]) -> None:
    assert not schema_accepts(payload), label
    assert not model_accepts(payload), label


def test_protocol_vocabularies_match_schema_and_documentation() -> None:
    schema_frame_kinds = SCHEMA["properties"]["frame_kind"]["enum"]
    assert schema_frame_kinds == [frame_kind.value for frame_kind in McuFrameKind]

    schema_ordinary_opcodes = SCHEMA["allOf"][0]["then"]["allOf"][1]["properties"]["opcode"]["enum"]
    model_ordinary_opcodes = [opcode.value for opcode in McuOpcode if opcode is not McuOpcode.STOP]
    assert schema_ordinary_opcodes == model_ordinary_opcodes
    assert SCHEMA["allOf"][3]["then"]["allOf"][0]["properties"]["opcode"] == {"const": McuOpcode.STOP.value}

    assert SCHEMA["properties"]["device_mode"]["enum"] == [mode.value for mode in McuDeviceMode]

    schema_fault_codes = SCHEMA["properties"]["fault_code"]["enum"]
    assert schema_fault_codes == [fault.value for fault in McuFaultCode]
    for fault_code in schema_fault_codes:
        assert PROTOCOL_DOC.count(f"| `{fault_code}` |") == 1


def test_downstream_safety_semantics_are_explicitly_frozen() -> None:
    normalized_doc = " ".join(PROTOCOL_DOC.split())
    required_semantics = [
        "delta = (candidate - last_accepted) mod 32768",
        "delta = (candidate - last_accepted) mod 4294967296",
        "including the wrap from 32767 to 0",
        "must not execute side effects again",
        "retry_count` echoes the received request",
        "must not subtract timestamps from different senders",
        "duplicate, retry and stale frames do not",
        "does not define a reset frame or reset opcode",
        "must not derive reset authority solely from any",
    ]
    for semantic in required_semantics:
        assert semantic in normalized_doc


@pytest.mark.parametrize(
    ("last_accepted", "candidate", "expected"),
    [
        (32766, 32767, "newer"),
        (32767, 0, "newer"),
        (0, 1, "newer"),
        (0, 16383, "newer"),
        (0, 0, "duplicate"),
        (0, 16384, "stale_or_ambiguous"),
        (0, 32767, "stale_or_ambiguous"),
        (1, 0, "stale_or_ambiguous"),
    ],
)
def test_ordinary_command_serial_half_range_vectors(last_accepted: int, candidate: int, expected: str) -> None:
    assert classify_ordinary_serial(last_accepted, candidate) == expected


@pytest.mark.parametrize(
    ("last_accepted", "candidate", "expected"),
    [
        (4294967294, 4294967295, "newer"),
        (4294967295, 0, "newer"),
        (0, 1, "newer"),
        (0, 2147483647, "newer"),
        (0, 0, "duplicate"),
        (0, 2147483648, "stale_or_ambiguous"),
        (0, 4294967295, "stale_or_ambiguous"),
        (1, 0, "stale_or_ambiguous"),
    ],
)
def test_telemetry_sequence_half_range_vectors(last_accepted: int, candidate: int, expected: str) -> None:
    assert classify_telemetry_sequence(last_accepted, candidate) == expected


def test_repository_schema_compiler_accepts_protocol_metadata(tmp_path: Path) -> None:
    compiler = SchemaCompiler(ROOT / "interfaces" / "json_schema")
    compiler.load_schemas()
    compiler.compile_all(tmp_path / "python", tmp_path / "typescript")

    generated = tmp_path / "python" / "mcu_protocol.py"
    namespace: dict[str, object] = {}
    exec(compile(generated.read_text(encoding="utf-8"), str(generated), "exec"), namespace)
    generated_model = namespace["McuFrame"]
    generated_model(frame_id="f", frame_kind="command", command_id=32767, sent_at="compat")
    generated_model(frame_id="f", frame_kind="stop", command_id=32768, sent_at="compat")


def test_committed_stop_ack_round_trips_through_schema_and_model() -> None:
    payload = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))

    assert schema_accepts(payload)
    frame = McuFrame.model_validate(payload)
    assert isinstance(frame.root, McuStopAckFrame)
    assert frame.model_dump(mode="json") == payload
