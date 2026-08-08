"""Unit tests that always exercise packages from this checkout."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for relative_path in (
    "libs/contracts",
    "services/agent_runtime",
    "services/backend",
    "services/world_model",
    "firmware/virtual_mcu",
):
    local_path = str(ROOT / relative_path)
    if local_path not in sys.path:
        sys.path.insert(0, local_path)
