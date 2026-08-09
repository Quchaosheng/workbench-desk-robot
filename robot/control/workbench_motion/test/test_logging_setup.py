"""Unit tests for the unified logging configuration.

Proves the phase-0 acceptance criterion: the unified format carries run_id and
the setup is idempotent (no stacked handlers, no reliance on ``print``).
"""

from __future__ import annotations

import io
import logging

from workbench_motion.logging_setup import (
    LOG_FORMAT,
    _ContextDefaultsFilter,
    configure_logging,
    get_action_logger,
)


def _capture_handler(logger: logging.Logger) -> io.StringIO:
    """Attach a StringIO handler mirroring the unified format + context filter.

    We cannot rely on capsys/capfd here: the real StreamHandler binds sys.stderr
    at construction, before pytest swaps the stream, so capsys never sees it.
    This handler captures deterministically while exercising the same LOG_FORMAT
    and defaults filter the package installs.
    """
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.addFilter(_ContextDefaultsFilter())
    logger.addHandler(handler)
    return stream


def test_configure_is_idempotent() -> None:
    logger = logging.getLogger("workbench_motion")
    configure_logging()
    count_after_first = len(logger.handlers)
    configure_logging()
    count_after_second = len(logger.handlers)
    assert count_after_first == count_after_second


def test_package_logger_does_not_propagate_to_root() -> None:
    configure_logging()
    assert logging.getLogger("workbench_motion").propagate is False


def test_format_carries_run_and_action_ids() -> None:
    configure_logging()
    logger = logging.getLogger("workbench_motion.fmt")
    stream = _capture_handler(logger)
    log = get_action_logger("workbench_motion.fmt", run_id="run-xyz", action_id="act-7")
    log.info("action started")
    line = stream.getvalue()
    assert "run=run-xyz" in line
    assert "action=act-7" in line
    assert "action started" in line


def test_plain_log_without_context_uses_defaults() -> None:
    configure_logging()
    logger = logging.getLogger("workbench_motion.plain")
    stream = _capture_handler(logger)
    logger.warning("no context here")
    line = stream.getvalue()
    # The context filter must supply defaults so the formatter never crashes.
    assert "run=-" in line
    assert "action=-" in line
