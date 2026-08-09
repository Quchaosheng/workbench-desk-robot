"""Shared validation and aggregation for performance evidence."""

from __future__ import annotations

import hashlib
import json
import math
import platform
from collections import defaultdict
from pathlib import Path
from typing import Any

REQUIRED_TELEMETRY_FIELDS = {
    "timestamp",
    "level",
    "service",
    "source",
    "run_id",
    "sequence_no",
    "event",
    "message",
    "details",
}
ALLOWED_SOURCES = {"simulation", "hardware"}
MEMORY_UNITS = {
    "b": 1,
    "kb": 1000,
    "kib": 1024,
    "mb": 1000**2,
    "mib": 1024**2,
    "gb": 1000**3,
    "gib": 1024**3,
}


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    if not 0 < quantile <= 1:
        raise ValueError("quantile must be in (0, 1]")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _telemetry_paths(inputs: list[Path]) -> list[Path]:
    paths: list[Path] = []
    for item in inputs:
        if item.is_dir():
            paths.extend(sorted(item.glob("*.jsonl")))
        elif item.is_file():
            paths.append(item)
        else:
            raise RuntimeError(f"telemetry input does not exist: {item}")
    if not paths:
        raise RuntimeError("no telemetry JSONL files were found")
    return paths


def load_telemetry(inputs: list[Path]) -> tuple[list[dict[str, Any]], list[Path]]:
    records: list[dict[str, Any]] = []
    paths = _telemetry_paths(inputs)
    for path in paths:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSON at {path}:{line_number}") from exc
            if not isinstance(record, dict) or not REQUIRED_TELEMETRY_FIELDS.issubset(record):
                raise RuntimeError(f"invalid telemetry fields at {path}:{line_number}")
            if record["source"] not in ALLOWED_SOURCES:
                raise RuntimeError(f"unknown telemetry source at {path}:{line_number}")
            if type(record["sequence_no"]) is not int or record["sequence_no"] < 0:
                raise RuntimeError(f"invalid telemetry sequence at {path}:{line_number}")
            if not isinstance(record["details"], dict):
                raise RuntimeError(f"telemetry details must be an object at {path}:{line_number}")
            records.append(record)
    sequences: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for record in records:
        sequences[(record["source"], record["service"], record["run_id"])].append(record["sequence_no"])
    for key, values in sequences.items():
        if values != list(range(len(values))):
            raise RuntimeError(f"non-contiguous telemetry sequence for {key}")
    return records, paths


def validate_hardware_evidence(paths: list[Path], evidence_path: Path | None) -> dict[str, Any] | None:
    if evidence_path is None:
        return None
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    required = {"evidence_kind", "hardware_id", "operator", "captured_at", "logs"}
    if not isinstance(evidence, dict) or not required.issubset(evidence):
        raise RuntimeError("hardware evidence manifest is missing required fields")
    if evidence["evidence_kind"] != "operator_attested_real_hardware":
        raise RuntimeError("hardware evidence manifest has the wrong evidence_kind")
    expected = evidence["logs"]
    if not isinstance(expected, dict):
        raise RuntimeError("hardware evidence logs must map file names to SHA-256 digests")
    actual = {path.name: file_sha256(path) for path in paths}
    if actual != expected:
        raise RuntimeError("hardware evidence log hashes do not match the analyzed files")
    return evidence


def summarize_telemetry(
    records: list[dict[str, Any]],
    *,
    hardware_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stage_values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for record in records:
        if record["event"] != "stage_completed":
            continue
        stage = record["details"].get("stage")
        duration_ms = record["details"].get("duration_ms")
        if not isinstance(stage, str) or not stage or type(duration_ms) not in (int, float) or duration_ms < 0:
            raise RuntimeError("stage_completed records require a stage and non-negative duration_ms")
        stage_values[record["source"]][stage].append(float(duration_ms))
    if not stage_values:
        raise RuntimeError("telemetry contains no stage_completed samples")
    if "hardware" in stage_values and hardware_evidence is None:
        raise RuntimeError("hardware telemetry requires a hash-verified operator evidence manifest")
    sources: dict[str, Any] = {}
    for source, stages in sorted(stage_values.items()):
        sources[source] = {
            "stages": {
                stage: {
                    "samples": len(values),
                    "p50_ms": percentile(values, 0.50),
                    "p95_ms": percentile(values, 0.95),
                    "max_ms": max(values),
                }
                for stage, values in sorted(stages.items())
            }
        }
    return {
        "schema_version": 1,
        "generated_by": "tools/scripts/analyze_telemetry.py",
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "record_count": len(records),
        "sources": sources,
        "hardware_evidence": (
            {
                "verified": True,
                "hardware_id": hardware_evidence["hardware_id"],
                "operator": hardware_evidence["operator"],
                "captured_at": hardware_evidence["captured_at"],
            }
            if hardware_evidence
            else {"verified": False}
        ),
    }


def parse_memory_bytes(value: str) -> int:
    normalized = value.strip().replace(" ", "")
    split_at = next((index for index, char in enumerate(normalized) if char.isalpha()), len(normalized))
    number = normalized[:split_at]
    unit = normalized[split_at:].lower() or "b"
    if not number or unit not in MEMORY_UNITS:
        raise ValueError(f"unsupported memory value: {value}")
    return round(float(number) * MEMORY_UNITS[unit])


def summarize_resource_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, float]]] = defaultdict(list)
    for sample in samples:
        name = sample.get("Name") or sample.get("Container")
        if not isinstance(name, str) or not name:
            raise RuntimeError("docker stats sample has no container name")
        try:
            cpu = float(str(sample["CPUPerc"]).rstrip("%"))
            memory = parse_memory_bytes(str(sample["MemUsage"]).split("/")[0])
        except (KeyError, ValueError) as exc:
            raise RuntimeError(f"invalid docker stats sample for {name}") from exc
        grouped[name].append({"cpu_percent": cpu, "memory_bytes": float(memory)})
    return {
        name: {
            "samples": len(values),
            "cpu_percent_p50": percentile([item["cpu_percent"] for item in values], 0.50),
            "cpu_percent_p95": percentile([item["cpu_percent"] for item in values], 0.95),
            "cpu_percent_max": max(item["cpu_percent"] for item in values),
            "memory_bytes_p50": percentile([item["memory_bytes"] for item in values], 0.50),
            "memory_bytes_p95": percentile([item["memory_bytes"] for item in values], 0.95),
            "memory_bytes_max": max(item["memory_bytes"] for item in values),
        }
        for name, values in sorted(grouped.items())
    }
