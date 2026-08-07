import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def enable_local_packages() -> Path:
    for relative_path in [
        "libs/contracts",
        "services/agent_runtime",
        "services/world_model",
        "firmware/virtual_mcu",
    ]:
        path = str(ROOT / relative_path)
        if path not in sys.path:
            sys.path.insert(0, path)
    return ROOT
