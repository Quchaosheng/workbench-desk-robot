from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    OBSERVE = "observe"
    GRASP = "grasp"
    PLACE = "place"
    ASK_CONFIRM = "ask_confirm"
    EXPRESS = "express"
    STOP = "stop"


class ActionStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class WorldEventType(str, Enum):
    OBSERVATION = "observation"
    ACTION_REQUEST = "action_request"
    ACTION_RESULT = "action_result"
    VERIFICATION = "verification"
    FAULT = "fault"


class ClockId(str, Enum):
    MONOTONIC = "monotonic"
    WALL = "wall"


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


class Detector(str, Enum):
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


class ActionOutcome(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    SAFE_STOP = "safe_stop"
    TIMEOUT = "timeout"


class DispatchState(str, Enum):
    """Whether the frame left the host. Not whether the device acted on it."""

    NOT_SENT = "not_sent"
    SENT = "sent"
    SEND_FAILED = "send_failed"


class DeviceState(str, Enum):
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


class VerificationStatus(str, Enum):
    """Three-valued on purpose. A boolean would force the system to guess when
    the evidence does not support either answer."""

    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ReasonCode(str, Enum):
    GOAL_SATISFIED = "goal_satisfied"
    GOAL_NOT_SATISFIED = "goal_not_satisfied"
    TARGET_NOT_OBSERVED = "target_not_observed"
    CONFIDENCE_BELOW_THRESHOLD = "confidence_below_threshold"
    CONFLICTING_OBSERVATIONS = "conflicting_observations"
    EVIDENCE_MISSING = "evidence_missing"
    STALE_OBSERVATION = "stale_observation"


class RecoveryHint(str, Enum):
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
