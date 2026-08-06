import json
import sys
import threading
from datetime import UTC, datetime
from typing import Any, TextIO


class StructuredLogger:
    """Emit one stable JSON object per line for simulation and hardware services."""

    def __init__(self, service: str, stream: TextIO | None = None) -> None:
        self.service = service
        self.stream = stream or sys.stdout
        self._sequences: dict[str, int] = {}
        self._lock = threading.Lock()

    def emit(
        self,
        event: str,
        message: str,
        *,
        run_id: str = "system",
        level: str = "INFO",
        source: str = "simulation",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            sequence_no = self._sequences.get(run_id, 0)
            self._sequences[run_id] = sequence_no + 1
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": level.upper(),
            "service": self.service,
            "source": source,
            "run_id": run_id,
            "sequence_no": sequence_no,
            "event": event,
            "message": message,
            "details": details or {},
        }
        self.stream.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")
        self.stream.flush()
        return record
