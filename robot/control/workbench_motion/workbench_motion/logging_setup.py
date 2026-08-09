"""Unified logging configuration for the Motion package.

Rules (see robot/control/PLAN.md, "全局约定"):
- Every module uses ``logging.getLogger(__name__)``; ``print`` is never used.
- Levels: DEBUG planning detail / INFO action start-stop / WARNING retry-degrade
  / ERROR failure-and-rejection.
- Every action log line carries ``run_id`` + ``action_id`` for human trace-back.

Logs are for humans and debugging. They are deliberately NOT the evidence
channel: anything referenced by ``evidence_refs`` must have a stable id and go
through :mod:`workbench_motion.evidence`, not a log line.
"""

from __future__ import annotations

import logging

# Fields we always want present on a record so the formatter never crashes on a
# plain ``logger.info(...)`` call that did not supply action context.
_DEFAULT_CONTEXT = {"run_id": "-", "action_id": "-"}

LOG_FORMAT = "%(asctime)s %(levelname)s [run=%(run_id)s action=%(action_id)s] %(name)s: %(message)s"


class _ContextDefaultsFilter(logging.Filter):
    """Fill in ``run_id``/``action_id`` defaults for records that omit them."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in _DEFAULT_CONTEXT.items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Install the unified handler + formatter on the ``workbench_motion`` logger.

    Idempotent: calling it more than once does not stack handlers. Attaches to
    the package logger (not the root) so the host application keeps control of
    global logging config.
    """
    logger = logging.getLogger("workbench_motion")
    logger.setLevel(level)
    logger.propagate = False

    if any(getattr(h, "_workbench_motion", False) for h in logger.handlers):
        return

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.addFilter(_ContextDefaultsFilter())
    handler._workbench_motion = True  # type: ignore[attr-defined]  # marker for idempotency
    logger.addHandler(handler)


def get_action_logger(name: str, *, run_id: str, action_id: str = "-") -> logging.LoggerAdapter:
    """Return a logger adapter that stamps ``run_id``/``action_id`` on every line.

    Use one per action so all of an action's log lines carry the same ids.
    """
    return logging.LoggerAdapter(logging.getLogger(name), {"run_id": run_id, "action_id": action_id})
