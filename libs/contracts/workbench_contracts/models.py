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


class ActionResult(BaseModel):
    action_id: str
    status: ActionStatus
    detail: str = ""
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


class VerificationResult(BaseModel):
    task_id: str
    completed: bool
    reason: str
    rule_version: str
    evidence_refs: list[str] = Field(default_factory=list)


class ScenarioManifest(BaseModel):
    scenario_id: str
    seed: int
    task_id: str
    world_version: str
    fault_type: str = "none"
    timeout_s: int = Field(gt=0, le=600)
    oracle_allowed: bool = False
