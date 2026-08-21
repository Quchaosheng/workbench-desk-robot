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

from dataclasses import dataclass

from workbench_contracts import TaskGraph, TaskStep

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
        result = self._registry.validate(action)
        return [PolicyFinding(step.step_id, action.action_id, error.field, error.message) for error in result.errors]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _format_findings(findings: tuple[PolicyFinding, ...]) -> str:
    lines = []
    for finding in findings:
        loc = f"step '{finding.step_id}'" if finding.step_id else "step '(unknown)'"
        lines.append(f"{loc} action '{finding.action_id}': {finding.field}: {finding.message}")
    return "TaskGraph violates tool whitelist:\n" + "\n".join(lines)
