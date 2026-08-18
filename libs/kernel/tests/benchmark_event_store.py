"""Small reproducible SQLite event-store benchmark; no third-party runner needed."""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workbench.kernel.event_store import EventStore


def event(index: int) -> dict:
    return {
        "event_id": f"bench-{index}",
        "run_id": "benchmark",
        "sequence_no": index,
        "event_type": "observation",
        "occurred_at": "2026-08-18T00:00:00Z",
        "payload": {"index": index},
        "evidence_refs": [],
    }


def main() -> int:
    count = 250
    with tempfile.TemporaryDirectory() as directory:
        store = EventStore(Path(directory) / "events.sqlite3")
        started = time.perf_counter()
        store.append_many([event(index) for index in range(count)])
        append_seconds = time.perf_counter() - started
        started = time.perf_counter()
        replayed = store.replay()
        replay_seconds = time.perf_counter() - started
        assert len(replayed) == count
        print(f"sqlite append: {count / append_seconds:.1f} events/s")
        print(f"sqlite replay: {count / replay_seconds:.1f} events/s")
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
