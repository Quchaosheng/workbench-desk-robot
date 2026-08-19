"""Bounded, in-process health metrics and snapshots.

The collector is deliberately pull-driven: an owner records samples from its
existing component or OS adapter, then asks for a snapshot. There is no
monitoring thread, network exporter, or unbounded time-series buffer here.
"""

from __future__ import annotations

import math
import re
import shutil
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from itertools import pairwise
from pathlib import Path
from typing import Any


class MetricError(ValueError):
    """Raised when a metric or sample violates the monitoring contract."""


class MetricKind(StrEnum):
    GAUGE = "gauge"
    COUNTER = "counter"
    HISTOGRAM = "histogram"


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAULT = "fault"
    UNKNOWN = "unknown"


def _matches(value: object, candidates: tuple[Any, ...]) -> bool:
    return any(type(value) is type(candidate) and value == candidate for candidate in candidates)


def _finite_number(value: object) -> bool:
    if type(value) not in {int, float}:
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _elapsed(current: int | float, previous: int | float) -> float:
    elapsed = current - previous
    if not _finite_number(elapsed):
        raise MetricError("monotonic time difference must be finite")
    return float(elapsed)


def _valid_type(value_type: str, value: object) -> bool:
    if value_type == "bool":
        return type(value) is bool
    if value_type == "int":
        return type(value) is int and -(2**63) <= value < 2**63
    if value_type == "float":
        return _finite_number(value)
    return type(value) is str and bool(value) and len(value) <= 128 and "\n" not in value and "\r" not in value


@dataclass(frozen=True)
class MetricSpec:
    name: str
    kind: MetricKind
    unit: str
    domain: str
    value_type: str
    freshness_s: float
    critical: bool = False
    fault_values: tuple[Any, ...] = ()
    degraded_values: tuple[Any, ...] = ()
    allowed_values: tuple[Any, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    allowed_labels: tuple[str, ...] = ()
    source: str = "component"
    value_pattern: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.name) is not str
            or len(self.name) > 80
            or not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+", self.name)
        ):
            raise MetricError(f"invalid metric name: {self.name!r}")
        if not isinstance(self.kind, MetricKind):
            raise MetricError(f"invalid metric kind: {self.kind!r}")
        if type(self.value_type) is not str or self.value_type not in {"bool", "int", "float", "str"}:
            raise MetricError(f"unsupported metric value type: {self.value_type!r}")
        if type(self.critical) is not bool:
            raise MetricError(f"metric criticality must be boolean: {self.name!r}")
        if self.kind is MetricKind.COUNTER and self.value_type != "int":
            raise MetricError(f"counter metric {self.name!r} must use integer values")
        if self.kind is MetricKind.HISTOGRAM and self.value_type not in {"int", "float"}:
            raise MetricError(f"histogram metric {self.name!r} must use numeric values")
        value_sets = (self.fault_values, self.degraded_values, self.allowed_values)
        if any(type(values) is not tuple or len(values) > 32 for values in value_sets):
            raise MetricError(f"metric {self.name!r} has an unbounded value set")
        if (
            any(
                type(value) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}", value)
                for value in (self.domain, self.unit, self.source)
            )
            or not _finite_number(self.freshness_s)
            or not 0.1 <= self.freshness_s <= 86_400
        ):
            raise MetricError("metric domain, unit, source, and freshness_s must be bounded and non-empty")
        configured_values = self.fault_values + self.degraded_values + self.allowed_values
        if any(not _valid_type(self.value_type, value) for value in configured_values):
            raise MetricError(f"configured values have the wrong type for metric {self.name!r}")
        if type(self.allowed_labels) is not tuple or any(type(label) is not str for label in self.allowed_labels):
            raise MetricError(f"invalid labels for metric {self.name!r}")
        if len(set(self.allowed_labels)) != len(self.allowed_labels):
            raise MetricError(f"duplicate labels for metric {self.name!r}")
        if len(self.allowed_labels) > 4 or any(
            not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", label) or label in {"le", "value"}
            for label in self.allowed_labels
        ):
            raise MetricError(f"invalid labels for metric {self.name!r}")
        if (self.minimum is not None or self.maximum is not None) and self.value_type not in {"int", "float"}:
            raise MetricError(f"non-numeric metric {self.name!r} cannot have a range")
        if any(not _finite_number(limit) for limit in (self.minimum, self.maximum) if limit is not None):
            raise MetricError(f"metric {self.name!r} has a non-finite range")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise MetricError(f"invalid range for metric {self.name!r}")
        if any(_matches(value, self.degraded_values) for value in self.fault_values):
            raise MetricError(f"fault and degraded values overlap for metric {self.name!r}")
        if self.allowed_values and any(
            not _matches(value, self.allowed_values) for value in self.fault_values + self.degraded_values
        ):
            raise MetricError(f"health values must be allowed for metric {self.name!r}")
        if self.value_pattern is not None:
            if self.value_type != "str" or type(self.value_pattern) is not str or len(self.value_pattern) > 256:
                raise MetricError(f"invalid value pattern for metric {self.name!r}")
            try:
                re.compile(self.value_pattern)
            except re.error as exc:
                raise MetricError(f"invalid value pattern for metric {self.name!r}") from exc
        if self.value_type == "str" and not self.allowed_values and self.value_pattern is None:
            raise MetricError(f"string metric {self.name!r} must use an enum or identifier pattern")


@dataclass(frozen=True)
class MetricSample:
    name: str
    value: bool | int | float | str
    observed_at: float
    source: str
    labels: tuple[tuple[str, str], ...] = ()
    clock_id: str = "monotonic"


@dataclass(frozen=True)
class MetricView:
    name: str
    value: bool | int | float | str | None
    unit: str
    expected_source: str
    source: str | None
    observed_at: float | None
    age_s: float | None
    state: str
    source_status: str
    missing: bool = False
    stale: bool = False


@dataclass(frozen=True)
class DomainHealth:
    status: HealthStatus
    metrics: tuple[MetricView, ...]


@dataclass(frozen=True)
class HealthSnapshot:
    collected_at: float
    clock_id: str
    overall: HealthStatus
    domains: tuple[tuple[str, DomainHealth], ...]

    def domain(self, name: str) -> DomainHealth:
        for domain, health in self.domains:
            if domain == name:
                return health
        raise KeyError(name)

    def as_dict(self) -> dict[str, Any]:
        return {
            "collected_at": self.collected_at,
            "clock_id": self.clock_id,
            "overall": self.overall.value,
            "domains": {
                domain: {
                    "status": health.status.value,
                    "metrics": [asdict(metric) for metric in health.metrics],
                }
                for domain, health in self.domains
            },
        }


def _validate_value(spec: MetricSpec, value: object) -> bool | int | float | str:
    if not _valid_type(spec.value_type, value):
        raise MetricError(f"{spec.name} expects a finite {spec.value_type}")
    if spec.allowed_values and not _matches(value, spec.allowed_values):
        raise MetricError(f"{spec.name} has an unsupported value")
    if spec.value_pattern is not None and not re.fullmatch(spec.value_pattern, value):  # type: ignore[arg-type]
        raise MetricError(f"{spec.name} has an invalid string value")
    if spec.minimum is not None and float(value) < spec.minimum:
        raise MetricError(f"{spec.name} is below its minimum")
    if spec.maximum is not None and float(value) > spec.maximum:
        raise MetricError(f"{spec.name} is above its maximum")
    return value  # type: ignore[return-value]


def _labels(spec: MetricSpec, labels: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
    if labels is not None and not isinstance(labels, Mapping):
        raise MetricError(f"labels for {spec.name} must be a mapping")
    values = {} if labels is None else dict(labels)
    unknown = set(values) - set(spec.allowed_labels)
    if unknown:
        raise MetricError(f"unknown labels for {spec.name}: {sorted(unknown)}")
    if len(values) > 4 or any(type(key) is not str or type(value) is not str for key, value in values.items()):
        raise MetricError(f"labels for {spec.name} must be a bounded string mapping")
    if any(
        not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", key) or not value or len(value) > 64 or "\n" in value or "\r" in value
        for key, value in values.items()
    ):
        raise MetricError(f"labels for {spec.name} contain an invalid value")
    return tuple(sorted(values.items()))


DEFAULT_SPECS = (
    MetricSpec(
        "app.readiness",
        MetricKind.GAUGE,
        "bool",
        "application",
        "bool",
        5.0,
        degraded_values=(False,),
        source="application",
    ),
    MetricSpec(
        "app.uptime_seconds", MetricKind.GAUGE, "seconds", "application", "float", 10.0, minimum=0, source="application"
    ),
    MetricSpec(
        "app.restart_count", MetricKind.COUNTER, "restarts", "application", "int", 60.0, minimum=0, source="supervisor"
    ),
    MetricSpec(
        "app.queue_depth", MetricKind.GAUGE, "items", "application", "int", 10.0, minimum=0, source="application"
    ),
    MetricSpec(
        "app.last_successful_cycle_age_seconds",
        MetricKind.GAUGE,
        "seconds",
        "application",
        "float",
        10.0,
        minimum=0,
        source="application",
    ),
    MetricSpec(
        "compute.cpu_percent",
        MetricKind.GAUGE,
        "percent",
        "compute",
        "float",
        10.0,
        minimum=0,
        maximum=100,
        source="linux.proc",
    ),
    MetricSpec(
        "compute.memory_percent",
        MetricKind.GAUGE,
        "percent",
        "compute",
        "float",
        10.0,
        minimum=0,
        maximum=100,
        source="linux.proc",
    ),
    MetricSpec(
        "compute.disk_free_bytes",
        MetricKind.GAUGE,
        "bytes",
        "compute",
        "int",
        30.0,
        minimum=0,
        source="linux.statvfs",
    ),
    MetricSpec(
        "compute.disk_growth_bytes",
        MetricKind.GAUGE,
        "bytes",
        "compute",
        "int",
        30.0,
        source="linux.statvfs",
    ),
    MetricSpec("compute.load_1m", MetricKind.GAUGE, "load", "compute", "float", 10.0, minimum=0, source="linux.proc"),
    MetricSpec(
        "compute.temperature_celsius",
        MetricKind.GAUGE,
        "celsius",
        "compute",
        "float",
        30.0,
        source="linux.sysfs",
    ),
    MetricSpec(
        "safety.estop_channels_ok",
        MetricKind.GAUGE,
        "bool",
        "safety",
        "bool",
        1.0,
        True,
        (False,),
        source="safety_mcu",
    ),
    MetricSpec(
        "safety.mcu_watchdog_ok",
        MetricKind.GAUGE,
        "bool",
        "safety",
        "bool",
        1.0,
        True,
        (False,),
        source="safety_mcu",
    ),
    MetricSpec(
        "safety.contactor_permission",
        MetricKind.GAUGE,
        "bool",
        "safety",
        "bool",
        1.0,
        True,
        source="safety_mcu",
    ),
    MetricSpec(
        "power.bms_state",
        MetricKind.GAUGE,
        "state",
        "power",
        "str",
        5.0,
        True,
        ("FAULT_LATCHED",),
        ("DERATE",),
        ("OFF", "SELF_TEST", "STANDBY", "PRECHARGE", "RUN", "CHARGE", "DERATE", "FAULT_LATCHED", "SERVICE"),
        source="bms",
    ),
    MetricSpec(
        "power.soc_percent",
        MetricKind.GAUGE,
        "percent",
        "power",
        "float",
        30.0,
        minimum=0,
        maximum=100,
        source="bms",
    ),
    MetricSpec(
        "power.pack_voltage_volts",
        MetricKind.GAUGE,
        "volts",
        "power",
        "float",
        10.0,
        minimum=0,
        source="bms",
    ),
    MetricSpec("power.pack_current_amperes", MetricKind.GAUGE, "amperes", "power", "float", 10.0, source="bms"),
    MetricSpec("power.pack_temperature_celsius", MetricKind.GAUGE, "celsius", "power", "float", 10.0, source="bms"),
    MetricSpec("can.link_ok", MetricKind.GAUGE, "bool", "communication", "bool", 1.0, True, (False,), source="can"),
    MetricSpec(
        "can.bus_state",
        MetricKind.GAUGE,
        "state",
        "communication",
        "str",
        1.0,
        True,
        ("bus-off", "error"),
        ("warning",),
        ("active", "warning", "bus-off", "error"),
        source="can",
    ),
    MetricSpec("can.error_count", MetricKind.COUNTER, "errors", "communication", "int", 10.0, minimum=0, source="can"),
    MetricSpec(
        "can.last_frame_age_seconds",
        MetricKind.GAUGE,
        "seconds",
        "communication",
        "float",
        1.0,
        minimum=0,
        source="can",
    ),
    MetricSpec(
        "event_store.integrity_ok",
        MetricKind.GAUGE,
        "bool",
        "communication",
        "bool",
        5.0,
        True,
        (False,),
        source="event_store",
    ),
    MetricSpec(
        "backend.available",
        MetricKind.GAUGE,
        "bool",
        "communication",
        "bool",
        5.0,
        degraded_values=(False,),
        source="backend",
    ),
    MetricSpec("nav.localization_ok", MetricKind.GAUGE, "bool", "robot", "bool", 1.0, True, (False,), source="nav2"),
    MetricSpec("motion.controller_ok", MetricKind.GAUGE, "bool", "robot", "bool", 1.0, True, (False,), source="motion"),
    MetricSpec(
        "motion.stop_state",
        MetricKind.GAUGE,
        "state",
        "robot",
        "str",
        1.0,
        True,
        ("fault",),
        ("requested",),
        ("idle", "requested", "confirmed", "fault"),
        source="motion",
    ),
    MetricSpec("perception.fresh", MetricKind.GAUGE, "bool", "robot", "bool", 1.0, True, (False,), source="perception"),
    MetricSpec("task.active", MetricKind.GAUGE, "bool", "task", "bool", 10.0, source="agent_runtime"),
    MetricSpec(
        "task.run_id",
        MetricKind.GAUGE,
        "id",
        "task",
        "str",
        10.0,
        source="agent_runtime",
        value_pattern=r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}",
    ),
    MetricSpec(
        "task.action_id",
        MetricKind.GAUGE,
        "id",
        "task",
        "str",
        10.0,
        source="agent_runtime",
        value_pattern=r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}",
    ),
    MetricSpec(
        "task.verification_state",
        MetricKind.GAUGE,
        "state",
        "task",
        "str",
        10.0,
        allowed_values=("none", "running", "confirmed", "refuted", "insufficient_evidence"),
        source="world_model",
    ),
    MetricSpec(
        "task.timeout_count",
        MetricKind.COUNTER,
        "timeouts",
        "task",
        "int",
        60.0,
        minimum=0,
        source="agent_runtime",
    ),
    MetricSpec(
        "task.fault_count",
        MetricKind.COUNTER,
        "faults",
        "task",
        "int",
        60.0,
        minimum=0,
        source="agent_runtime",
    ),
)


class MetricRegistry:
    """Fixed metric definitions; no dynamic production registration."""

    def __init__(self, specs: tuple[MetricSpec, ...] = DEFAULT_SPECS) -> None:
        if (
            type(specs) is not tuple
            or not 1 <= len(specs) <= 256
            or any(not isinstance(spec, MetricSpec) for spec in specs)
        ):
            raise MetricError("registry must contain between 1 and 256 metric specifications")
        names = [spec.name for spec in specs]
        if len(names) != len(set(names)):
            raise MetricError("duplicate metric registration")
        projected = [name.replace(".", "_") for name in names]
        if len(projected) != len(set(projected)):
            raise MetricError("metric names collide in Prometheus projection")
        self._specs = {spec.name: spec for spec in specs}

    def get(self, name: str) -> MetricSpec:
        try:
            return self._specs[name]
        except KeyError:
            raise MetricError(f"unknown metric: {name!r}") from None

    def specs(self) -> tuple[MetricSpec, ...]:
        return tuple(self._specs.values())


class SystemMetrics:
    """Thread-safe bounded metric storage with a Prometheus text projection."""

    def __init__(
        self,
        registry: MetricRegistry | None = None,
        *,
        histogram_buckets: tuple[float, ...] = (0.01, 0.05, 0.1, 0.5, 1.0),
        max_series: int = 256,
    ) -> None:
        if (
            type(histogram_buckets) is not tuple
            or not 1 <= len(histogram_buckets) <= 64
            or any(not _finite_number(bucket) or bucket <= 0 for bucket in histogram_buckets)
            or any(left >= right for left, right in pairwise(histogram_buckets))
        ):
            raise MetricError("histogram buckets must be positive finite values")
        if type(max_series) is not int or not 1 <= max_series <= 1024:
            raise MetricError("max_series must be between 1 and 1024")
        self.registry = registry or MetricRegistry()
        self.histogram_buckets = histogram_buckets
        self.max_series = max_series
        self._samples: dict[tuple[str, tuple[tuple[str, str], ...]], MetricSample] = {}
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[int, float, list[int]]] = {}
        self._conflicts: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
        self._lock = threading.RLock()

    def _make_sample(
        self,
        name: str,
        value: object,
        *,
        source: str,
        observed_at: float,
        labels: Mapping[str, str] | None,
    ) -> MetricSample:
        spec = self.registry.get(name)
        if source != spec.source:
            raise MetricError(f"{name} expects source {spec.source!r}")
        if not _finite_number(observed_at):
            raise MetricError("observed_at must be finite")
        return MetricSample(name, _validate_value(spec, value), float(observed_at), source, _labels(spec, labels))

    def _record(
        self,
        name: str,
        value: object,
        *,
        source: str,
        observed_at: float,
        labels: Mapping[str, str] | None,
        allow_same_timestamp_update: bool = False,
    ) -> MetricSample:
        spec = self.registry.get(name)
        sample = self._make_sample(name, value, source=source, observed_at=observed_at, labels=labels)
        with self._lock:
            key = (name, sample.labels)
            if key not in self._samples and len(self._samples) >= self.max_series:
                raise MetricError("metric series limit reached")
            current = self._samples.get(key)
            if current is not None:
                if sample.observed_at < current.observed_at:
                    raise MetricError("metric timestamp regressed")
                if (
                    sample.observed_at == current.observed_at
                    and not allow_same_timestamp_update
                    and not _matches(sample.value, (current.value,))
                ):
                    self._conflicts.add(key)
                    raise MetricError("metric values conflict at the same timestamp")
                if spec.kind is MetricKind.COUNTER and sample.value < current.value:  # type: ignore[operator]
                    raise MetricError("counter value regressed")
                if sample.observed_at > current.observed_at:
                    self._conflicts.discard(key)
            self._samples[key] = sample
        return sample

    def set_gauge(
        self,
        name: str,
        value: object,
        *,
        source: str | None = None,
        observed_at: float | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        spec = self.registry.get(name)
        if spec.kind is not MetricKind.GAUGE:
            raise MetricError(f"{name} is not a gauge")
        self._record(
            name,
            value,
            source=spec.source if source is None else source,
            observed_at=time.monotonic() if observed_at is None else observed_at,
            labels=labels,
        )

    def increment_counter(
        self,
        name: str,
        value: int = 1,
        *,
        source: str | None = None,
        observed_at: float | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        spec = self.registry.get(name)
        if spec.kind is not MetricKind.COUNTER or type(value) is not int or value < 0:
            raise MetricError(f"{name} is not a non-negative integer counter")
        normalized_labels = _labels(spec, labels)
        key = (name, normalized_labels)
        with self._lock:
            current = self._samples.get(key)
            total = int(current.value) if current else 0
            self._record(
                name,
                total + value,
                source=spec.source if source is None else source,
                observed_at=time.monotonic() if observed_at is None else observed_at,
                labels=dict(normalized_labels),
                allow_same_timestamp_update=True,
            )

    def set_counter(
        self,
        name: str,
        value: object,
        *,
        source: str | None = None,
        observed_at: float | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        spec = self.registry.get(name)
        if spec.kind is not MetricKind.COUNTER or type(value) is not int or value < 0:
            raise MetricError(f"{name} is not a non-negative integer counter")
        self._record(
            name,
            value,
            source=spec.source if source is None else source,
            observed_at=time.monotonic() if observed_at is None else observed_at,
            labels=labels,
        )

    def record_histogram(
        self,
        name: str,
        value: object,
        *,
        source: str | None = None,
        observed_at: float | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        spec = self.registry.get(name)
        if spec.kind is not MetricKind.HISTOGRAM:
            raise MetricError(f"{name} is not a finite histogram")
        sample = self._make_sample(
            name,
            value,
            source=spec.source if source is None else source,
            observed_at=time.monotonic() if observed_at is None else observed_at,
            labels=labels,
        )
        key = (name, sample.labels)
        with self._lock:
            if key not in self._samples and len(self._samples) >= self.max_series:
                raise MetricError("metric series limit reached")
            current = self._samples.get(key)
            if current is not None and sample.observed_at < current.observed_at:
                raise MetricError("metric timestamp regressed")
            numeric_value = float(sample.value)
            count, total, buckets = self._histograms.get(key, (0, 0.0, [0] * len(self.histogram_buckets)))
            if count >= 2**63 - 1:
                raise MetricError("histogram count limit reached")
            new_total = total + numeric_value
            if not math.isfinite(new_total):
                raise MetricError("histogram aggregate is not finite")
            buckets = buckets.copy()
            for index, bucket in enumerate(self.histogram_buckets):
                if numeric_value <= bucket:
                    buckets[index] += 1
            self._samples[key] = sample
            self._histograms[key] = (count + 1, new_total, buckets)

    def samples(self) -> tuple[MetricSample, ...]:
        with self._lock:
            return tuple(self._samples.values())

    def current_state(
        self,
    ) -> tuple[tuple[MetricSample, ...], frozenset[tuple[str, tuple[tuple[str, str], ...]]]]:
        with self._lock:
            return tuple(self._samples.values()), frozenset(self._conflicts)

    def export_prometheus(self) -> str:
        with self._lock:
            samples = tuple(self._samples.values())
            conflicts = frozenset(self._conflicts)
            histograms = {
                key: (count, total, tuple(buckets)) for key, (count, total, buckets) in self._histograms.items()
            }
        lines: list[str] = []
        for sample in sorted(samples, key=lambda item: (item.name, item.labels)):
            if (sample.name, sample.labels) in conflicts:
                continue
            spec = self.registry.get(sample.name)
            name = sample.name.replace(".", "_")
            labels = _format_labels(sample.labels)
            if spec.kind is MetricKind.HISTOGRAM:
                count, total, counts = histograms[(sample.name, sample.labels)]
                for bucket, bucket_count in zip(self.histogram_buckets, counts, strict=True):
                    lines.append(f"{name}_bucket{_format_labels((*sample.labels, ('le', str(bucket))))} {bucket_count}")
                lines.append(f"{name}_bucket{_format_labels((*sample.labels, ('le', '+Inf')))} {count}")
                lines.append(f"{name}_count{labels} {count}")
                lines.append(f"{name}_sum{labels} {total}")
            else:
                if type(sample.value) is str:
                    if spec.allowed_values:
                        lines.append(f"{name}{_format_labels((*sample.labels, ('value', sample.value)))} 1")
                else:
                    value = int(sample.value) if type(sample.value) is bool else sample.value
                    lines.append(f"{name}{labels} {value}")
        return "\n".join(lines) + ("\n" if lines else "")


def _format_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    encoded = []
    for key, value in sorted(labels):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        encoded.append(f'{key}="{escaped}"')
    return "{" + ",".join(encoded) + "}"


class HealthSnapshotCollector:
    """Evaluate current fixed-registry samples without owning a scheduler."""

    def __init__(
        self,
        metrics: SystemMetrics | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sampling_interval_s: float = 1.0,
    ) -> None:
        if not _finite_number(sampling_interval_s) or not 0.1 <= sampling_interval_s <= 3_600:
            raise MetricError("sampling_interval_s must be between 0.1 and 3600 seconds")
        self.metrics = metrics or SystemMetrics()
        if any(spec.allowed_labels for spec in self.metrics.registry.specs()):
            raise MetricError("health snapshots require one unlabelled series per metric")
        self.clock = clock
        self.sampling_interval_s = float(sampling_interval_s)

    def is_due(self, last_collected_at: float | None, *, now: float | None = None) -> bool:
        current = self.clock() if now is None else now
        if not _finite_number(current):
            raise MetricError("current monotonic time must be finite")
        if last_collected_at is None:
            return True
        if not _finite_number(last_collected_at):
            raise MetricError("last collected monotonic time must be finite")
        if current < last_collected_at:
            raise MetricError("monotonic clock regressed")
        return _elapsed(current, last_collected_at) >= self.sampling_interval_s

    def record(
        self,
        name: str,
        value: object,
        *,
        source: str,
        observed_at: float | None = None,
        clock_id: str = "monotonic",
        labels: Mapping[str, str] | None = None,
    ) -> None:
        if clock_id != "monotonic":
            raise MetricError("only monotonic samples can be compared")
        spec = self.metrics.registry.get(name)
        timestamp = self.clock() if observed_at is None else observed_at
        if spec.kind is MetricKind.GAUGE:
            self.metrics.set_gauge(name, value, source=source, observed_at=timestamp, labels=labels)
        elif spec.kind is MetricKind.COUNTER:
            self.metrics.set_counter(name, value, source=source, observed_at=timestamp, labels=labels)
        else:
            self.metrics.record_histogram(name, value, source=source, observed_at=timestamp, labels=labels)

    def snapshot(self, *, collected_at: float | None = None) -> HealthSnapshot:
        now = self.clock() if collected_at is None else collected_at
        if not _finite_number(now):
            raise MetricError("collected_at must be finite")
        current_samples, conflicts = self.metrics.current_state()
        samples = {(sample.name, sample.labels): sample for sample in current_samples}
        domains: dict[str, list[MetricView]] = {}
        domain_states: dict[str, list[HealthStatus]] = {}
        for spec in self.metrics.registry.specs():
            sample = samples.get((spec.name, ()))
            views = domains.setdefault(spec.domain, [])
            states = domain_states.setdefault(spec.domain, [])
            if sample is None:
                view = MetricView(spec.name, None, spec.unit, spec.source, None, None, None, "missing", "missing", True)
                states.append(HealthStatus.UNKNOWN if spec.critical else HealthStatus.DEGRADED)
            else:
                age = _elapsed(now, sample.observed_at)
                stale = age < 0 or sample.clock_id != "monotonic" or age > spec.freshness_s
                conflict = (spec.name, ()) in conflicts
                fault = _matches(sample.value, spec.fault_values)
                degraded = _matches(sample.value, spec.degraded_values)
                state = (
                    "conflict"
                    if conflict
                    else "fault"
                    if fault
                    else "stale"
                    if stale
                    else "degraded"
                    if degraded
                    else "fresh"
                )
                view = MetricView(
                    spec.name,
                    None if conflict else sample.value,
                    spec.unit,
                    spec.source,
                    sample.source,
                    sample.observed_at,
                    age,
                    state,
                    "conflict" if conflict else "stale" if stale else "available",
                    stale=stale,
                )
                states.append(
                    HealthStatus.FAULT
                    if (conflict and spec.critical) or fault
                    else HealthStatus.UNKNOWN
                    if stale and spec.critical
                    else HealthStatus.DEGRADED
                    if conflict or stale or degraded
                    else HealthStatus.HEALTHY
                )
            views.append(view)
        result = []
        for domain in sorted(domains):
            result.append((domain, DomainHealth(_worst(domain_states[domain]), tuple(domains[domain]))))
        return HealthSnapshot(float(now), "monotonic", _worst([health.status for _, health in result]), tuple(result))


def _worst(states: list[HealthStatus]) -> HealthStatus:
    for status in (HealthStatus.FAULT, HealthStatus.UNKNOWN, HealthStatus.DEGRADED, HealthStatus.HEALTHY):
        if status in states:
            return status
    return HealthStatus.UNKNOWN


class LinuxHealthAdapter:
    """Pull bounded host metrics from injectable procfs/sysfs readers."""

    def __init__(
        self,
        *,
        read_text: Callable[[str], str] | None = None,
        disk_usage: Callable[[str], tuple[int, int, int]] = shutil.disk_usage,
        disk_path: str = "/",
        thermal_path: str = "/sys/class/thermal/thermal_zone0/temp",
    ) -> None:
        self.read_text = read_text or (lambda path: Path(path).read_text(encoding="utf-8"))
        self.disk_usage = disk_usage
        self.disk_path = disk_path
        self.thermal_path = thermal_path
        self._cpu_ticks: tuple[int, int] | None = None
        self._disk_used: int | None = None
        self._lock = threading.Lock()

    def collect(self, collector: HealthSnapshotCollector, *, observed_at: float | None = None) -> tuple[str, ...]:
        timestamp = collector.clock() if observed_at is None else observed_at
        collected: list[str] = []

        def record(name: str, value: object, source: str) -> None:
            collector.record(name, value, source=source, observed_at=timestamp)
            collected.append(name)

        try:
            values = {
                line.split(":", 1)[0]: int(line.split()[1])
                for line in self.read_text("/proc/meminfo").splitlines()
                if ":" in line and len(line.split()) >= 2
            }
            memory_percent = 100.0 * (values["MemTotal"] - values["MemAvailable"]) / values["MemTotal"]
            record("compute.memory_percent", memory_percent, "linux.proc")
        except (OSError, TypeError, ValueError, KeyError, ZeroDivisionError):
            pass

        try:
            record("compute.load_1m", float(self.read_text("/proc/loadavg").split()[0]), "linux.proc")
        except (OSError, TypeError, ValueError, IndexError):
            pass

        try:
            fields = [int(value) for value in self.read_text("/proc/stat").splitlines()[0].split()[1:9]]
            total, idle = sum(fields), fields[3] + fields[4]
            with self._lock:
                previous = self._cpu_ticks
                self._cpu_ticks = (total, idle)
            if previous is not None and total > previous[0]:
                cpu_percent = 100.0 * (1.0 - (idle - previous[1]) / (total - previous[0]))
                record("compute.cpu_percent", min(100.0, max(0.0, cpu_percent)), "linux.proc")
        except (OSError, TypeError, ValueError, IndexError):
            pass

        try:
            _total, used, free = self.disk_usage(self.disk_path)
            with self._lock:
                previous_used = self._disk_used
                self._disk_used = used
            record("compute.disk_free_bytes", free, "linux.statvfs")
            if previous_used is not None:
                record("compute.disk_growth_bytes", used - previous_used, "linux.statvfs")
        except (OSError, TypeError, ValueError):
            pass

        try:
            temperature = float(self.read_text(self.thermal_path).strip())
            record(
                "compute.temperature_celsius",
                temperature / 1_000,
                "linux.sysfs",
            )
        except (OSError, TypeError, ValueError):
            pass

        return tuple(collected)


class ComponentHealthAdapter:
    """Pull a bounded set of component or ROS-diagnostic readers."""

    def __init__(self, source: str, readers: Mapping[str, Callable[[], object]]) -> None:
        if type(source) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}", source):
            raise MetricError("adapter source must be a bounded identifier")
        if not isinstance(readers, Mapping) or not 1 <= len(readers) <= 32:
            raise MetricError("adapter requires between 1 and 32 readers")
        if any(type(name) is not str or not callable(reader) for name, reader in readers.items()):
            raise MetricError("adapter readers must map metric names to callables")
        self.source = source
        self.readers = tuple(sorted(readers.items()))
        self._lock = threading.Lock()

    def collect(self, collector: HealthSnapshotCollector, *, observed_at: float | None = None) -> tuple[str, ...]:
        timestamp = collector.clock() if observed_at is None else observed_at
        collected = []
        with self._lock:
            for name, reader in self.readers:
                spec = collector.metrics.registry.get(name)
                if spec.source != self.source:
                    raise MetricError(f"{name} does not belong to source {self.source!r}")
                try:
                    value = reader()
                except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
                    continue
                collector.record(name, value, source=self.source, observed_at=timestamp)
                collected.append(name)
        return tuple(collected)


system_metrics = SystemMetrics()
