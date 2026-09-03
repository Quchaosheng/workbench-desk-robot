"""Run an external RLSOK standalone Shadow check and verify its evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_INPUT_BYTES = 1 * 1024 * 1024
MAX_PROCESS_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_EVIDENCE_BYTES = 8 * 1024 * 1024
MAX_COMMAND_TOKENS = 16


class RlsokShadowError(RuntimeError):
    """RLSOK failed or returned output that cannot be trusted."""


class RlsokShadowUnavailable(RlsokShadowError):
    """The configured RLSOK command could not be started."""


class _DuplicateJsonKey(ValueError):
    pass


@dataclass(frozen=True)
class RlsokShadowResult:
    """Verified local record of one zero-dispatch Shadow evaluation."""

    decision: str
    reason: str
    controller_goals_attempted: int
    hardware_signal_sent: bool
    release_id: str
    executable_policy_hash: str
    evidence_path: Path
    evidence_sha256: str
    evidence_ref: str
    verification_output: str


@dataclass(frozen=True)
class _ProcessResult:
    returncode: int
    stdout: str
    stderr: str


class RlsokShadowRunner:
    """Invoke only the standalone Shadow and evidence-verification commands."""

    def __init__(self, command: Sequence[str] = ("rlsok",), *, timeout_seconds: float = 30.0) -> None:
        tokens = tuple(command)
        if not tokens or len(tokens) > MAX_COMMAND_TOKENS:
            raise ValueError(f"command must contain 1-{MAX_COMMAND_TOKENS} tokens")
        if any(not isinstance(token, str) or not token or "\x00" in token for token in tokens):
            raise ValueError("command tokens must be non-empty strings without NUL bytes")
        if timeout_seconds <= 0 or timeout_seconds > 600:
            raise ValueError("timeout_seconds must be between 0 and 600")
        self._command = tokens
        self._timeout_seconds = timeout_seconds

    def run(self, release_path: Path, proposal_path: Path, evidence_path: Path) -> RlsokShadowResult:
        """Run Shadow, require zero dispatch, then verify the EvidenceBundle."""
        release = _validate_input_file(release_path, "release")
        proposal = _validate_input_file(proposal_path, "proposal")
        evidence = Path(evidence_path).resolve()
        if evidence.exists():
            raise RlsokShadowError(f"refusing to overwrite existing evidence: {evidence}")

        shadow = _run_bounded(
            (*self._command, "shadow", str(release), str(proposal), str(evidence)),
            timeout_seconds=self._timeout_seconds,
        )
        if shadow.returncode != 0:
            raise RlsokShadowError(_command_failure("RLSOK Shadow", shadow))

        summary = _parse_summary(shadow.stdout)
        _validate_shadow_summary(summary, evidence)
        bundle = _load_evidence(evidence)

        verification = _run_bounded(
            (*self._command, "verify-evidence", str(evidence), "--release", str(release)),
            timeout_seconds=self._timeout_seconds,
        )
        if verification.returncode != 0:
            raise RlsokShadowError(_command_failure("RLSOK evidence verification", verification))

        digest = _sha256(evidence)
        return RlsokShadowResult(
            decision=summary["decision"],
            reason=summary["reason"],
            controller_goals_attempted=0,
            hardware_signal_sent=False,
            release_id=bundle["releaseId"],
            executable_policy_hash=bundle["executablePolicyHash"],
            evidence_path=evidence,
            evidence_sha256=digest,
            evidence_ref=f"rlsok://evidence/sha256/{digest}",
            verification_output=verification.stdout.strip(),
        )


def _validate_input_file(path: Path, label: str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise RlsokShadowError(f"{label} input is not a file: {resolved}")
    if resolved.stat().st_size > MAX_INPUT_BYTES:
        raise RlsokShadowError(f"{label} input exceeds {MAX_INPUT_BYTES} bytes")
    return resolved


def _run_bounded(command: Sequence[str], *, timeout_seconds: float) -> _ProcessResult:
    with tempfile.TemporaryDirectory(prefix="workbench-rlsok-") as directory:
        stdout_path = Path(directory) / "stdout.log"
        stderr_path = Path(directory) / "stderr.log"
        try:
            with stdout_path.open("wb") as stdout_stream, stderr_path.open("wb") as stderr_stream:
                process = subprocess.Popen(command, stdout=stdout_stream, stderr=stderr_stream, shell=False)
                deadline = time.monotonic() + timeout_seconds
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        process.kill()
                        process.wait()
                        raise RlsokShadowError(f"RLSOK command timed out after {timeout_seconds:g} seconds")
                    if _output_too_large(stdout_path, stderr_path):
                        process.kill()
                        process.wait()
                        raise RlsokShadowError("RLSOK command output exceeded the configured limit")
                    time.sleep(0.02)
        except FileNotFoundError as error:
            raise RlsokShadowUnavailable(f"RLSOK command is unavailable: {command[0]}") from error

        if _output_too_large(stdout_path, stderr_path):
            raise RlsokShadowError("RLSOK command output exceeded the configured limit")
        return _ProcessResult(
            returncode=process.returncode,
            stdout=stdout_path.read_text(encoding="utf-8", errors="replace"),
            stderr=stderr_path.read_text(encoding="utf-8", errors="replace"),
        )


def _output_too_large(stdout_path: Path, stderr_path: Path) -> bool:
    return any(path.exists() and path.stat().st_size > MAX_PROCESS_OUTPUT_BYTES for path in (stdout_path, stderr_path))


def _command_failure(label: str, result: _ProcessResult) -> str:
    detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
    return f"{label} failed with exit code {result.returncode}: {detail[:1000]}"


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _parse_summary(stdout: str) -> dict[str, Any]:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise RlsokShadowError("RLSOK Shadow returned no summary")
    try:
        summary = json.loads(lines[-1], object_pairs_hook=_object_without_duplicates)
    except (_DuplicateJsonKey, json.JSONDecodeError) as error:
        raise RlsokShadowError("RLSOK Shadow summary is not strict JSON") from error
    if not isinstance(summary, dict):
        raise RlsokShadowError("RLSOK Shadow summary must be a JSON object")
    return summary


def _validate_shadow_summary(summary: dict[str, Any], evidence_path: Path) -> None:
    if summary.get("mode") != "standalone":
        raise RlsokShadowError("RLSOK result is not a standalone Shadow evaluation")
    if not isinstance(summary.get("decision"), str) or not summary["decision"]:
        raise RlsokShadowError("RLSOK result is missing a decision")
    if not isinstance(summary.get("reason"), str) or not summary["reason"]:
        raise RlsokShadowError("RLSOK result is missing a reason")
    if type(summary.get("controllerGoalsAttempted")) is not int or summary["controllerGoalsAttempted"] != 0:
        raise RlsokShadowError("RLSOK Shadow attempted or ambiguously reported controller goals")
    if summary.get("hardwareSignalSent") is not False:
        raise RlsokShadowError("RLSOK Shadow attempted or ambiguously reported a hardware signal")
    reported_path = summary.get("evidencePath")
    if not isinstance(reported_path, str) or Path(reported_path).resolve() != evidence_path:
        raise RlsokShadowError("RLSOK Shadow reported a different evidence path")


def _load_evidence(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RlsokShadowError("RLSOK Shadow did not create an EvidenceBundle")
    if path.stat().st_size > MAX_EVIDENCE_BYTES:
        raise RlsokShadowError(f"RLSOK EvidenceBundle exceeds {MAX_EVIDENCE_BYTES} bytes")
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object_without_duplicates)
    except (OSError, UnicodeError, _DuplicateJsonKey, json.JSONDecodeError) as error:
        raise RlsokShadowError("RLSOK EvidenceBundle is not strict UTF-8 JSON") from error
    if not isinstance(bundle, dict) or bundle.get("kind") != "EvidenceBundle":
        raise RlsokShadowError("RLSOK evidence has the wrong kind")
    for field in ("releaseId", "executablePolicyHash"):
        if not isinstance(bundle.get(field), str) or not bundle[field]:
            raise RlsokShadowError(f"RLSOK EvidenceBundle is missing {field}")
    entries = bundle.get("entries")
    if not isinstance(entries, list) or not entries:
        raise RlsokShadowError("RLSOK EvidenceBundle must contain at least one entry")
    for entry in entries:
        evidence = entry.get("evidence") if isinstance(entry, dict) else None
        if not isinstance(evidence, dict) or evidence.get("hardwareSignalSent") is not False:
            raise RlsokShadowError("RLSOK evidence does not prove hardwareSignalSent false")
    return bundle


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
