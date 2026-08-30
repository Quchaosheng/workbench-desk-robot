"""Deterministic software boundary for known-target RGB-D observations.

This module deliberately does not claim a connected camera or ROS runtime.  It
turns already-synchronised RGB, aligned-depth and AprilTag inputs into the
existing Observation contract, retaining only bounded immutable frame metadata.
"""

from __future__ import annotations

import hashlib
import math
import struct
from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Final

from workbench_contracts import ClockId, Detector, Observation, Orientation, Pose, Position

_POSE_UNITS: Final = "m"


class RgbdObservationRejected(ValueError):
    """A frame pair failed a known-target RGB-D boundary check."""


@dataclass(frozen=True)
class KnownEntity:
    """One configured AprilTag identity; unknown tags are never guessed."""

    tag_id: int
    entity_id: str
    entity_type: str

    def __post_init__(self) -> None:
        if isinstance(self.tag_id, bool) or not isinstance(self.tag_id, int) or self.tag_id < 0:
            raise ValueError("tag_id must be a non-negative integer")
        _require_text(self.entity_id, "entity_id")
        _require_text(self.entity_type, "entity_type")


@dataclass(frozen=True)
class CameraIntrinsics:
    """Validated pinhole intrinsics for one approved camera revision."""

    camera_id: str
    calibration_revision: str
    frame_id: str
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    clock_id: ClockId

    def __post_init__(self) -> None:
        for name in ("camera_id", "calibration_revision", "frame_id"):
            _require_text(getattr(self, name), name)
        _require_dimensions(self.width, self.height, "camera intrinsics")
        for name in ("fx", "fy", "cx", "cy"):
            if not _finite_number(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if self.fx <= 0 or self.fy <= 0:
            raise ValueError("fx and fy must be positive")
        if not 0 <= self.cx < self.width or not 0 <= self.cy < self.height:
            raise ValueError("principal point must be inside the image")
        if not isinstance(self.clock_id, ClockId):
            raise ValueError("clock_id must be a ClockId")


@dataclass(frozen=True)
class RgbFrame:
    """One local RGB frame. Bytes are hashed but never embedded in observations."""

    sequence_no: int
    width: int
    height: int
    observed_at: datetime
    clock_id: ClockId
    data: bytes

    def __post_init__(self) -> None:
        _require_sequence(self.sequence_no, "RGB sequence_no")
        _require_dimensions(self.width, self.height, "RGB frame")
        _require_timestamp(self.observed_at, "RGB observed_at")
        if not isinstance(self.clock_id, ClockId):
            raise ValueError("RGB clock_id must be a ClockId")
        if not isinstance(self.data, bytes) or len(self.data) != self.width * self.height * 3:
            raise ValueError("RGB data must contain exactly width * height * 3 bytes")


@dataclass(frozen=True)
class DepthFrame:
    """Aligned depth in metres, stored row-major for deterministic local fixtures."""

    sequence_no: int
    width: int
    height: int
    observed_at: datetime
    clock_id: ClockId
    depth_m: tuple[tuple[float, ...], ...]

    def __post_init__(self) -> None:
        _require_sequence(self.sequence_no, "depth sequence_no")
        _require_dimensions(self.width, self.height, "depth frame")
        _require_timestamp(self.observed_at, "depth observed_at")
        if not isinstance(self.clock_id, ClockId):
            raise ValueError("depth clock_id must be a ClockId")
        if len(self.depth_m) != self.height or any(len(row) != self.width for row in self.depth_m):
            raise ValueError("depth_m dimensions must match the depth frame")


@dataclass(frozen=True)
class TagDetection:
    """Detector output required to identify and locate one configured tag."""

    tag_id: int
    center_x: float
    center_y: float
    decision_margin: float
    hamming: int = 0
    occluded: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.tag_id, bool) or not isinstance(self.tag_id, int) or self.tag_id < 0:
            raise ValueError("tag_id must be a non-negative integer")
        for name in ("center_x", "center_y", "decision_margin"):
            if not _finite_number(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if isinstance(self.hamming, bool) or not isinstance(self.hamming, int) or self.hamming < 0:
            raise ValueError("hamming must be a non-negative integer")
        if not isinstance(self.occluded, bool):
            raise ValueError("occluded must be a boolean")


@dataclass(frozen=True)
class FrameEvidence:
    """Immutable, bounded metadata for one frame pair; no raw image bytes."""

    reference: str
    camera_id: str
    calibration_revision: str
    rgb_sequence_no: int
    depth_sequence_no: int
    observed_at: str
    clock_id: str
    rgb_sha256: str
    depth_sha256: str
    width: int
    height: int


class FrameEvidenceStore:
    """Resolve recent evidence references without retaining sensor payloads."""

    def __init__(self, maximum_entries: int = 256) -> None:
        if isinstance(maximum_entries, bool) or not isinstance(maximum_entries, int) or maximum_entries < 1:
            raise ValueError("maximum_entries must be a positive integer")
        self._maximum_entries = maximum_entries
        self._entries: OrderedDict[str, FrameEvidence] = OrderedDict()
        self._lock = Lock()

    def add(self, evidence: FrameEvidence) -> None:
        if not isinstance(evidence, FrameEvidence):
            raise ValueError("evidence must be FrameEvidence")
        with self._lock:
            if evidence.reference in self._entries:
                raise RgbdObservationRejected("duplicate frame evidence reference")
            self._entries[evidence.reference] = evidence
            while len(self._entries) > self._maximum_entries:
                self._entries.popitem(last=False)

    def resolve(self, reference: str) -> FrameEvidence | None:
        with self._lock:
            return self._entries.get(reference)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


@dataclass(frozen=True)
class ProducedObservation:
    """A contract Observation plus the #72 ingestion boundary arguments."""

    observation: Observation
    camera_id: str
    calibration_revision: str
    pose_units: str = _POSE_UNITS


@dataclass(frozen=True)
class ProductionBatch:
    """Atomic result for one frame pair."""

    observations: tuple[ProducedObservation, ...]
    ignored_tag_ids: tuple[int, ...]
    evidence_ref: str


class KnownTargetRgbdProducer:
    """Produce contract-valid observations for an explicit AprilTag allow-list."""

    def __init__(
        self,
        known_entities: Iterable[KnownEntity],
        *,
        now: Callable[[ClockId], datetime],
        evidence_store: FrameEvidenceStore,
        minimum_decision_margin: float = 50.0,
        maximum_hamming: int = 0,
        maximum_pair_skew: timedelta = timedelta(milliseconds=20),
        maximum_age: timedelta = timedelta(seconds=1),
        minimum_depth_m: float = 0.05,
        maximum_depth_m: float = 10.0,
    ) -> None:
        entities: dict[int, KnownEntity] = {}
        identities: set[str] = set()
        for entity in known_entities:
            if not isinstance(entity, KnownEntity):
                raise ValueError("known_entities must contain KnownEntity values")
            if entity.tag_id in entities:
                raise ValueError(f"duplicate configured tag_id {entity.tag_id}")
            if entity.entity_id in identities:
                raise ValueError(f"duplicate configured entity_id {entity.entity_id!r}")
            entities[entity.tag_id] = entity
            identities.add(entity.entity_id)
        if not entities:
            raise ValueError("at least one known entity is required")
        if not callable(now):
            raise ValueError("now must be callable")
        if not isinstance(evidence_store, FrameEvidenceStore):
            raise ValueError("evidence_store must be FrameEvidenceStore")
        if not _finite_number(minimum_decision_margin) or minimum_decision_margin < 0:
            raise ValueError("minimum_decision_margin must be finite and non-negative")
        if isinstance(maximum_hamming, bool) or not isinstance(maximum_hamming, int) or maximum_hamming < 0:
            raise ValueError("maximum_hamming must be a non-negative integer")
        if not isinstance(maximum_pair_skew, timedelta) or maximum_pair_skew < timedelta(0):
            raise ValueError("maximum_pair_skew must be a non-negative timedelta")
        if not isinstance(maximum_age, timedelta) or maximum_age < timedelta(0):
            raise ValueError("maximum_age must be a non-negative timedelta")
        if not _finite_number(minimum_depth_m) or not _finite_number(maximum_depth_m):
            raise ValueError("depth bounds must be finite")
        if minimum_depth_m <= 0 or maximum_depth_m <= minimum_depth_m:
            raise ValueError("depth bounds must be positive and increasing")

        self._entities = entities
        self._now = now
        self._evidence_store = evidence_store
        self._minimum_decision_margin = float(minimum_decision_margin)
        self._maximum_hamming = maximum_hamming
        self._maximum_pair_skew = maximum_pair_skew
        self._maximum_age = maximum_age
        self._minimum_depth_m = float(minimum_depth_m)
        self._maximum_depth_m = float(maximum_depth_m)
        self._seen_pairs: set[tuple[int, int, str]] = set()
        self._lock = Lock()

    def produce(
        self,
        *,
        run_id: str,
        rgb: RgbFrame,
        depth: DepthFrame,
        intrinsics: CameraIntrinsics,
        detections: Sequence[TagDetection],
    ) -> ProductionBatch:
        """Validate one aligned frame pair and atomically produce observations."""
        _require_text(run_id, "run_id", rejection=True)
        if not isinstance(rgb, RgbFrame) or not isinstance(depth, DepthFrame):
            raise RgbdObservationRejected("rgb and depth must be typed frames")
        if not isinstance(intrinsics, CameraIntrinsics):
            raise RgbdObservationRejected("intrinsics must be CameraIntrinsics")
        if not isinstance(detections, Sequence) or isinstance(detections, str | bytes):
            raise RgbdObservationRejected("detections must be a sequence")
        if any(not isinstance(item, TagDetection) for item in detections):
            raise RgbdObservationRejected("detections must contain TagDetection values")

        self._validate_frame_pair(rgb, depth, intrinsics)
        tag_ids = [item.tag_id for item in detections]
        if len(tag_ids) != len(set(tag_ids)):
            raise RgbdObservationRejected("duplicate tag detections fail closed")

        known_detections: list[tuple[KnownEntity, TagDetection, float]] = []
        ignored: list[int] = []
        for detection in detections:
            entity = self._entities.get(detection.tag_id)
            if entity is None:
                ignored.append(detection.tag_id)
                continue
            if detection.occluded:
                raise RgbdObservationRejected(f"configured tag {detection.tag_id} is occluded")
            if detection.decision_margin < self._minimum_decision_margin:
                raise RgbdObservationRejected(f"configured tag {detection.tag_id} has low decision margin")
            if detection.hamming > self._maximum_hamming:
                raise RgbdObservationRejected(f"configured tag {detection.tag_id} exceeds hamming limit")
            pixel_x = _pixel_index(detection.center_x, intrinsics.width, "center_x")
            pixel_y = _pixel_index(detection.center_y, intrinsics.height, "center_y")
            distance = depth.depth_m[pixel_y][pixel_x]
            if not _finite_number(distance) or not self._minimum_depth_m <= distance <= self._maximum_depth_m:
                raise RgbdObservationRejected(f"configured tag {detection.tag_id} has invalid aligned depth")
            known_detections.append((entity, detection, float(distance)))

        evidence = _frame_evidence(rgb, depth, intrinsics)
        pair_key = (rgb.sequence_no, depth.sequence_no, evidence.reference)
        produced = tuple(
            self._produce_observation(run_id, intrinsics, evidence, entity, detection, distance)
            for entity, detection, distance in known_detections
        )
        with self._lock:
            if pair_key in self._seen_pairs:
                raise RgbdObservationRejected("duplicate RGB-D frame pair")
            self._evidence_store.add(evidence)
            self._seen_pairs.add(pair_key)
        return ProductionBatch(
            observations=produced,
            ignored_tag_ids=tuple(sorted(ignored)),
            evidence_ref=evidence.reference,
        )

    def _validate_frame_pair(self, rgb: RgbFrame, depth: DepthFrame, intrinsics: CameraIntrinsics) -> None:
        if (rgb.width, rgb.height) != (depth.width, depth.height) or (rgb.width, rgb.height) != (
            intrinsics.width,
            intrinsics.height,
        ):
            raise RgbdObservationRejected("RGB, aligned depth and intrinsics dimensions must match")
        if rgb.sequence_no != depth.sequence_no:
            raise RgbdObservationRejected("RGB and aligned depth sequence numbers must match")
        if rgb.clock_id is not depth.clock_id or rgb.clock_id is not intrinsics.clock_id:
            raise RgbdObservationRejected("RGB, depth and calibration clock domains must match")
        skew = abs(rgb.observed_at.astimezone(UTC) - depth.observed_at.astimezone(UTC))
        if skew > self._maximum_pair_skew:
            raise RgbdObservationRejected("RGB and aligned depth timestamps are unsynchronised")
        current = self._now(rgb.clock_id)
        if not isinstance(current, datetime) or current.tzinfo is None:
            raise RgbdObservationRejected("injected clock must return a timezone-aware datetime")
        observed_at = max(rgb.observed_at.astimezone(UTC), depth.observed_at.astimezone(UTC))
        age = current.astimezone(UTC) - observed_at
        if age < timedelta(0):
            raise RgbdObservationRejected("RGB-D frame pair is future-skewed")
        if age > self._maximum_age:
            raise RgbdObservationRejected("RGB-D frame pair is stale")

    @staticmethod
    def _produce_observation(
        run_id: str,
        intrinsics: CameraIntrinsics,
        evidence: FrameEvidence,
        entity: KnownEntity,
        detection: TagDetection,
        distance: float,
    ) -> ProducedObservation:
        x = (detection.center_x - intrinsics.cx) * distance / intrinsics.fx
        y = (detection.center_y - intrinsics.cy) * distance / intrinsics.fy
        identity_bytes = "\x1f".join((run_id, evidence.reference, str(detection.tag_id), entity.entity_id)).encode()
        observation_id = f"rgbd-{hashlib.sha256(identity_bytes).hexdigest()[:24]}"
        confidence = min(1.0, max(0.0, detection.decision_margin / 100.0))
        observation = Observation(
            observation_id=observation_id,
            run_id=run_id,
            entity_id=entity.entity_id,
            entity_type=entity.entity_type,
            pose=Pose(
                frame_id=intrinsics.frame_id,
                position=Position(x=x, y=y, z=distance),
                orientation=Orientation(x=0.0, y=0.0, z=0.0, w=1.0),
            ),
            confidence=confidence,
            detector=Detector.APRILTAG,
            hamming=detection.hamming,
            decision_margin=detection.decision_margin,
            observed_at=evidence.observed_at,
            clock_id=intrinsics.clock_id,
            source=intrinsics.camera_id,
            evidence_refs=[evidence.reference],
        )
        return ProducedObservation(
            observation=observation,
            camera_id=intrinsics.camera_id,
            calibration_revision=intrinsics.calibration_revision,
        )


def _frame_evidence(rgb: RgbFrame, depth: DepthFrame, intrinsics: CameraIntrinsics) -> FrameEvidence:
    rgb_digest = hashlib.sha256(rgb.data).hexdigest()
    depth_hash = hashlib.sha256()
    for row in depth.depth_m:
        for value in row:
            depth_hash.update(struct.pack("!d", float(value)))
    depth_digest = depth_hash.hexdigest()
    observed_at = max(rgb.observed_at.astimezone(UTC), depth.observed_at.astimezone(UTC))
    identity = "\x1f".join(
        (
            intrinsics.camera_id,
            intrinsics.calibration_revision,
            str(rgb.sequence_no),
            str(depth.sequence_no),
            _format_timestamp(observed_at),
            rgb_digest,
            depth_digest,
        )
    )
    reference = f"evidence://rgbd/{intrinsics.camera_id}/{hashlib.sha256(identity.encode()).hexdigest()}"
    return FrameEvidence(
        reference=reference,
        camera_id=intrinsics.camera_id,
        calibration_revision=intrinsics.calibration_revision,
        rgb_sequence_no=rgb.sequence_no,
        depth_sequence_no=depth.sequence_no,
        observed_at=_format_timestamp(observed_at),
        clock_id=intrinsics.clock_id.value,
        rgb_sha256=rgb_digest,
        depth_sha256=depth_digest,
        width=rgb.width,
        height=rgb.height,
    )


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _pixel_index(value: float, limit: int, name: str) -> int:
    if not 0 <= value < limit:
        raise RgbdObservationRejected(f"{name} must be inside the image")
    return min(limit - 1, int(math.floor(value + 0.5)))


def _require_text(value: object, name: str, *, rejection: bool = False) -> None:
    error = RgbdObservationRejected if rejection else ValueError
    if not isinstance(value, str) or not value.strip():
        raise error(f"{name} must be a non-empty string")


def _require_sequence(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_dimensions(width: object, height: object, name: str) -> None:
    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, int)
        or not isinstance(height, int)
        or width < 1
        or height < 1
    ):
        raise ValueError(f"{name} dimensions must be positive integers")


def _require_timestamp(value: object, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")


def _finite_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(float(value))
