"""Language-layer policy validator: exact field-set whitelist, fail-closed.

A5 validates the ``TaskGraph`` produced from a natural-language goal against the
tool whitelist before anything reaches Motion / the MCU.  It reads
``required_params`` / ``optional_params`` / ``param_types`` from
:class:`~workbench_agent_runtime.tool_registry.ToolRegistry` — the single source
of truth — and enforces **exact field-set equality**: every required key must be
present, and no key outside the allow-list may appear.

``bool`` is checked *before* ``int`` / ``float`` because ``isinstance(True, int)``
is ``True`` in Python; without that ordering a ``duration_ms=True`` would pass
an integer slot as ``1``.

Three rules this module obeys and never crosses:

1. **The model never touches joints.**  Only the six semantic actions
   (``observe``/``grasp``/``place``/``ask_confirm``/``express``/``stop``) are
   valid; any joint/firmware field is an allow-list violation and is rejected.
2. **Completion is judged only by the world-model verifier.**  This module never
   constructs a ``VerificationResult`` and never declares a task done.
3. **Success claims carry evidence.**  Out of scope here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from workbench_contracts import ActionType, TaskGraph, TaskStep

from .tool_registry import ToolRegistry

# ---------------------------------------------------------------------------
# public types
# ---------------------------------------------------------------------------


class PolicyViolation(RuntimeError):
    """A TaskGraph or action violates the tool whitelist (fail-closed)."""


@dataclass(frozen=True)
class PolicyFinding:
    """One whitelist violation, located to a step and field."""

    step_id: str
    action_id: str
    field: str
    message: str


@dataclass(frozen=True)
class PolicyReport:
    """Aggregated whitelist result for a TaskGraph."""

    findings: tuple[PolicyFinding, ...]

    @property
    def is_valid(self) -> bool:
        return not self.findings


# ---------------------------------------------------------------------------
# validator
# ---------------------------------------------------------------------------


class PolicyValidator:
    """Validate TaskGraphs against the tool whitelist with fail-closed semantics.

    The whitelist data lives in :class:`ToolRegistry`; this module holds no
    second copy of the field list.  Two entry points:

    * :meth:`check` returns a :class:`PolicyReport` (inspection, never raises).
    * :meth:`enforce` raises :class:`PolicyViolation` on the first invalid graph.
    """

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._registry = registry if registry is not None else ToolRegistry()

    # -- public API ----------------------------------------------------------

    def check(self, graph: TaskGraph) -> PolicyReport:
        """Return every whitelist violation across all steps (never raises)."""
        findings: list[PolicyFinding] = []
        for step in graph.steps:
            findings.extend(self._check_step(step))
        return PolicyReport(tuple(findings))

    def enforce(self, graph: TaskGraph) -> None:
        """Fail-closed: raise :class:`PolicyViolation` if any step is invalid."""
        report = self.check(graph)
        if not report.is_valid:
            raise PolicyViolation(_format_findings(report.findings))

    # -- internals -----------------------------------------------------------

    def _check_step(self, step: TaskStep) -> list[PolicyFinding]:
        action = step.action
        findings: list[PolicyFinding] = []
        step_id = step.step_id
        action_id = action.action_id

        # 0. action_type must be a registered ActionType
        if not isinstance(action.action_type, ActionType):
            return [
                PolicyFinding(
                    step_id,
                    action_id,
                    "action_type",
                    f"expected an ActionType enum member, got {type(action.action_type).__name__!r}",
                )
            ]
        if action.action_type not in self._registry.list_all():
            return [
                PolicyFinding(
                    step_id,
                    action_id,
                    "action_type",
                    f"unknown action_type '{action.action_type.value}'",
                )
            ]

        schema = self._registry.get(action.action_type)
        target_id_required: bool = schema.get("target_id_required", False)
        required: frozenset[str] = schema["required_params"]
        optional: frozenset[str] = schema["optional_params"]
        allowed: frozenset[str] = required | optional
        param_types: Mapping[str, type | object] = schema["param_types"]

        # 1. target_id requirement (physical-safety boundary)
        if target_id_required and (not isinstance(action.target_id, str) or not action.target_id.strip()):
            findings.append(
                PolicyFinding(
                    step_id,
                    action_id,
                    "target_id",
                    f"'{action.action_type.value}' requires a non-empty target_id",
                )
            )

        # 2. parameters must be a mapping — fail-closed on malformed input
        params = action.parameters
        if not isinstance(params, Mapping):
            findings.append(
                PolicyFinding(
                    step_id,
                    action_id,
                    "parameters",
                    f"expected a mapping, got {type(params).__name__!r}",
                )
            )
            return findings

        # 3. exact field-set equality: reject extra and missing keys
        actual_keys = set(params)
        extra = actual_keys - allowed
        missing = required - actual_keys
        if extra:
            findings.append(
                PolicyFinding(
                    step_id,
                    action_id,
                    "parameters",
                    f"forbidden keys for '{action.action_type.value}': {sorted(extra)}; allowed: {sorted(allowed)}",
                )
            )
        if missing:
            findings.append(
                PolicyFinding(
                    step_id,
                    action_id,
                    "parameters",
                    f"missing required keys for '{action.action_type.value}': {sorted(missing)}",
                )
            )

        # 4. type safety (bool-before-int) — only for keys in the allow-list
        for key, value in params.items():
            expected_type = param_types.get(key)
            if expected_type is None:
                # undeclared key — already reported as forbidden, or permissive
                continue
            type_error = _type_error(key, value, expected_type)
            if type_error is not None:
                findings.append(PolicyFinding(step_id, action_id, f"parameters.{key}", type_error))

        return findings


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _type_error(key: str, value: object, expected: type | object) -> str | None:
    """Return an error message if *value* violates *expected*; ``None`` if ok.

    ``bool`` is checked before ``int`` / ``float`` because ``bool`` subclasses
    ``int`` in Python.  ``duration_ms`` and any other integer slot must reject
    ``True`` / ``False`` rather than coercing them to ``1`` / ``0``.
    """
    if expected is bool:
        if not isinstance(value, bool):
            return f"expected bool, got {_type_label(value)}"
        return None
    if expected is int:
        if isinstance(value, bool):
            return "expected int, got bool (bool is not int)"
        if not isinstance(value, int):
            return f"expected int, got {_type_label(value)}"
        return None
    if expected is float:
        if isinstance(value, bool):
            return "expected float, got bool"
        if not isinstance(value, int | float):
            return f"expected float, got {_type_label(value)}"
        return None
    if expected is str:
        if not isinstance(value, str):
            return f"expected str, got {_type_label(value)}"
        return None
    if expected is list:
        if not isinstance(value, list):
            return f"expected list, got {_type_label(value)}"
        return None
    if not isinstance(value, expected):
        return f"expected {getattr(expected, '__name__', str(expected))}, got {_type_label(value)}"
    return None


def _type_label(value: object) -> str:
    if isinstance(value, bool):
        return "bool"
    return type(value).__name__


def _format_findings(findings: tuple[PolicyFinding, ...]) -> str:
    lines = []
    for finding in findings:
        loc = f"step '{finding.step_id}'" if finding.step_id else "step '(unknown)'"
        lines.append(f"{loc} action '{finding.action_id}': {finding.field}: {finding.message}")
    return "TaskGraph violates tool whitelist:\n" + "\n".join(lines)
