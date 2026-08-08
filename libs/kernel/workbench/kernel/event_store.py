"""K6-K7: Event Store"""

import json
from pathlib import Path
from typing import Any


class EventStore:
    def __init__(self, log_file: Path):
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.events = []
        self.checkpoints = []

    def append(self, event: dict[str, Any]):
        with open(self.log_file, "a") as f:
            f.write(json.dumps(event) + "\n")
        self.events.append(event)

    def create_checkpoint(self):
        checkpoint_id = len(self.events)
        self.checkpoints.append(checkpoint_id)
        return checkpoint_id

    def replay(self, from_checkpoint: int | None = None):
        if not self.log_file.exists():
            return []

        with open(self.log_file) as f:
            lines = f.readlines()

        start_idx = from_checkpoint or 0
        replayed = []
        for line in lines[start_idx:]:
            if line.strip():
                replayed.append(json.loads(line))
        return replayed

    def verify_integrity(self):
        if not self.log_file.exists():
            return True

        with open(self.log_file) as f:
            for line in f:
                if line.strip():
                    try:
                        json.loads(line)
                    except json.JSONDecodeError:
                        return False
        return True
