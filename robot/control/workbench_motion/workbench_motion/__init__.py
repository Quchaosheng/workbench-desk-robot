"""Motion (robot/control) semantic-action adapter package.

Phase 0 delivers only the engineering scaffold: unified logging setup and the
EvidenceSink interface plus a test double. No arm, MoveIt, or grasp logic yet.
"""

from .evidence import EvidenceRef, EvidenceSink, ExecutionEvent, FakeEvidenceSink
from .logging_setup import configure_logging, get_action_logger

__all__ = [
    "EvidenceRef",
    "EvidenceSink",
    "ExecutionEvent",
    "FakeEvidenceSink",
    "configure_logging",
    "get_action_logger",
]
