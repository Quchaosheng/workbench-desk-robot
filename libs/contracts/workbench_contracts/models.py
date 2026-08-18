from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StringConstraints, model_validator


class ActionType(StrEnum):
    OBSERVE = "observe"
    GRASP = "grasp"
    PLACE = "place"
    ASK_CONFIRM = "ask_confirm"
    EXPRESS = "express"
    STOP = "stop"


class ActionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class WorldEventType(StrEnum):
    OBSERVATION = "observation"
    ACTION_REQUEST = "action_request"
    ACTION_RESULT = "action_result"
    VERIFICATION = "verification"
    FAULT = "fault"


class ClockId(StrEnum):
    MONOTONIC = "monotonic"
    WALL = "wall"


class McuFrameKind(StrEnum):
    COMMAND = "command"
    ACK = "ack"
    TELEMETRY = "telemetry"
    STOP = "stop"
    STOP_ACK = "stop_ack"


class McuOpcode(StrEnum):
    MOVE = "move"
    GRIP_OPEN = "grip_open"
    GRIP_CLOSE = "grip_close"
    HOLD = "hold"
    STOP = "stop"
    HEARTBEAT = "heartbeat"


class McuFaultCode(StrEnum):
    NONE = "none"
    ACK_TIMEOUT = "ack_timeout"
    STOP_TIMEOUT = "stop_timeout"
    STOP_REJECTED = "stop_rejected"
    LINK_LOST = "link_lost"
    DUPLICATE_FRAME = "duplicate_frame"
    WATCHDOG_EXPIRED = "watchdog_expired"
    MALFORMED_FRAME = "malformed_frame"


class McuDeviceMode(StrEnum):
    IDLE = "idle"
    MOVING = "moving"
    HOLDING = "holding"
    STOPPED = "stopped"
    FAULTED = "faulted"


McuFrameId = Annotated[
    str,
    StringConstraints(
        min_length=11,
        max_length=74,
        pattern=r"^mcu-frame-[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$",
    ),
]
McuOrdinaryCommandId = Annotated[int, Field(strict=True, ge=0, le=32767)]
McuStopCommandId = Annotated[int, Field(strict=True, ge=32768, le=65535)]
McuSequenceNo = Annotated[int, Field(strict=True, ge=0, le=4294967295)]
McuRetryCount = Annotated[int, Field(strict=True, ge=0, le=255)]
McuMonotonicUs = Annotated[int, Field(strict=True, ge=0, le=18446744073709551615)]
McuOrdinaryOpcode = Literal["move", "grip_open", "grip_close", "hold", "heartbeat"]
McuResultCode = Literal[0, 1]


class _McuFrameBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: Literal["1.0"]
    frame_id: McuFrameId
    sent_at_us: McuMonotonicUs
    clock_id: Literal["monotonic"]


class McuCommandFrame(_McuFrameBase):
    frame_kind: Literal["command"]
    command_id: McuOrdinaryCommandId
    opcode: McuOrdinaryOpcode
    retry_count: McuRetryCount


class McuAckFrame(_McuFrameBase):
    frame_kind: Literal["ack"]
    command_id: McuOrdinaryCommandId
    opcode: McuOrdinaryOpcode
    result_code: McuResultCode
    fault_code: McuFaultCode
    device_mode: McuDeviceMode
    retry_count: McuRetryCount

    @model_validator(mode="after")
    def validate_result(self) -> "McuAckFrame":
        if self.result_code == 0:
            if self.fault_code is not McuFaultCode.NONE or self.device_mode is McuDeviceMode.FAULTED:
                raise ValueError("successful ack requires fault_code none and a non-faulted device_mode")
        elif (
            self.fault_code not in {McuFaultCode.DUPLICATE_FRAME, McuFaultCode.MALFORMED_FRAME}
            or self.device_mode is not McuDeviceMode.FAULTED
        ):
            raise ValueError("failed ack requires a command-rejection fault and faulted device_mode")
        return self


class McuTelemetryFrame(_McuFrameBase):
    frame_kind: Literal["telemetry"]
    sequence_no: McuSequenceNo
    fault_code: McuFaultCode
    device_mode: McuDeviceMode

    @model_validator(mode="after")
    def validate_fault_state(self) -> "McuTelemetryFrame":
        if self.fault_code not in {
            McuFaultCode.NONE,
            McuFaultCode.LINK_LOST,
            McuFaultCode.WATCHDOG_EXPIRED,
        }:
            raise ValueError("telemetry fault_code must describe an active device fault")
        if (self.fault_code is McuFaultCode.NONE) == (self.device_mode is McuDeviceMode.FAULTED):
            raise ValueError("telemetry requires faulted mode exactly when fault_code is not none")
        return self


class McuStopFrame(_McuFrameBase):
    frame_kind: Literal["stop"]
    command_id: McuStopCommandId
    opcode: Literal["stop"]
    retry_count: McuRetryCount


class McuStopAckFrame(_McuFrameBase):
    frame_kind: Literal["stop_ack"]
    command_id: McuStopCommandId
    opcode: Literal["stop"]
    result_code: McuResultCode
    fault_code: McuFaultCode
    device_mode: McuDeviceMode
    retry_count: McuRetryCount

    @model_validator(mode="after")
    def validate_stop_result(self) -> "McuStopAckFrame":
        if self.result_code == 0:
            if self.fault_code is not McuFaultCode.NONE or self.device_mode is not McuDeviceMode.STOPPED:
                raise ValueError("successful stop_ack requires fault_code none and stopped device_mode")
        elif self.fault_code is not McuFaultCode.STOP_REJECTED or self.device_mode is not McuDeviceMode.FAULTED:
            raise ValueError("failed stop_ack requires stop_rejected and faulted device_mode")
        return self


McuFrameValue = Annotated[
    McuCommandFrame | McuAckFrame | McuTelemetryFrame | McuStopFrame | McuStopAckFrame,
    Field(discriminator="frame_kind"),
]


class McuFrame(RootModel[McuFrameValue]):
    """Fail-closed MCU logical frame protocol v1.0."""


class Position(BaseModel):
    x: float
    y: float
    z: float


class Orientation(BaseModel):
    """Unit quaternion. A tabletop grasp needs orientation, not just a point."""

    x: float
    y: float
    z: float
    w: float


class Pose(BaseModel):
    frame_id: str
    position: Position
    orientation: Orientation


class Detector(StrEnum):
    APRILTAG = "apriltag"
    COLOUR_THRESHOLD = "colour_threshold"
    MOCK = "mock"


class Observation(BaseModel):
    observation_id: str
    run_id: str
    entity_id: str
    entity_type: str
    pose: Pose
    confidence: float = Field(ge=0.0, le=1.0)
    detector: Detector = Detector.MOCK
    hamming: int | None = None
    decision_margin: float | None = None
    observed_at: str
    clock_id: ClockId = ClockId.MONOTONIC
    source: str = "sensor"
    evidence_refs: list[str] = Field(min_length=1)


class SemanticAction(BaseModel):
    action_id: str
    action_type: ActionType
    target_id: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class ActionOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    SAFE_STOP = "safe_stop"
    TIMEOUT = "timeout"


class DispatchState(StrEnum):
    """Whether the frame left the host. Not whether the device acted on it."""

    NOT_SENT = "not_sent"
    SENT = "sent"
    SEND_FAILED = "send_failed"


class DeviceState(StrEnum):
    """Whether the device confirmed. Separate from DispatchState by design:
    a written frame is not a confirmed action."""

    UNCONFIRMED = "unconfirmed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    STOPPED = "stopped"


class ActionResult(BaseModel):
    result_id: str
    action_id: str
    run_id: str
    outcome: ActionOutcome
    dispatch_state: DispatchState
    device_state: DeviceState
    error_code: int | None = None
    error_reason: str | None = None
    started_at: str
    ended_at: str
    clock_id: ClockId = ClockId.MONOTONIC
    retry_count: int = Field(default=0, ge=0)
    entity_id: str | None = None
    resulting_location: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class WorldEvent(BaseModel):
    event_id: str
    run_id: str
    sequence_no: int = Field(ge=0)
    event_type: WorldEventType
    occurred_at: str
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)


class TaskStep(BaseModel):
    step_id: str
    action: SemanticAction
    depends_on: list[str] = Field(default_factory=list)


class TaskGraph(BaseModel):
    task_id: str
    goal: str
    steps: list[TaskStep]
    planner: str
    model_route: str = "template"


class VerificationStatus(StrEnum):
    """Three-valued on purpose. A boolean would force the system to guess when
    the evidence does not support either answer."""

    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ReasonCode(StrEnum):
    GOAL_SATISFIED = "goal_satisfied"
    GOAL_NOT_SATISFIED = "goal_not_satisfied"
    TARGET_NOT_OBSERVED = "target_not_observed"
    CONFIDENCE_BELOW_THRESHOLD = "confidence_below_threshold"
    CONFLICTING_OBSERVATIONS = "conflicting_observations"
    EVIDENCE_MISSING = "evidence_missing"
    STALE_OBSERVATION = "stale_observation"


class RecoveryHint(StrEnum):
    RE_OBSERVE = "re_observe"
    RETRY_ACTION = "retry_action"
    ASK_CONFIRM = "ask_confirm"
    ABORT = "abort"
    NONE = "none"


class VerificationResult(BaseModel):
    verification_id: str
    run_id: str
    task_id: str
    claim: str
    status: VerificationStatus
    reason_code: ReasonCode | None = None
    completeness: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_refs: list[str] = Field(min_length=1)
    recovery_hint: RecoveryHint = RecoveryHint.NONE
    verified_at: str
    clock_id: ClockId = ClockId.MONOTONIC
    rule_version: str = "unversioned"

    @property
    def completed(self) -> bool:
        """True only for a confirmed goal. Both `refuted` and
        `insufficient_evidence` are not-completed, but they are not the same
        thing — read `status` when the distinction matters."""
        return self.status is VerificationStatus.CONFIRMED

    @property
    def reason(self) -> str:
        return self.reason_code.value if self.reason_code else self.status.value


class ScenarioManifest(BaseModel):
    scenario_id: str
    seed: int
    task_id: str
    world_version: str
    fault_type: str = "none"
    timeout_s: int = Field(gt=0, le=600)
    oracle_allowed: bool = False
