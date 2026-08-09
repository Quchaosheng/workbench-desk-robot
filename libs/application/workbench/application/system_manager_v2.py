"""APP1: Production system manager"""

import logging
import threading
from enum import Enum

logger = logging.getLogger("SystemManager")


class ComponentState(Enum):
    CREATED = "created"
    RUNNING = "running"
    ERROR = "error"
    STOPPED = "stopped"


class SystemManager:
    """Thread-safe lifecycle management"""

    def __init__(self):
        self.components = {}
        self.lock = threading.RLock()
        self.state = "initialized"

    def register(self, name: str, instance) -> bool:
        with self.lock:
            if name in self.components:
                return False
            self.components[name] = {"state": ComponentState.CREATED, "instance": instance}
            logger.info(f"Registered: {name}")
            return True

    def startup(self) -> bool:
        with self.lock:
            for _name, comp in self.components.items():
                if hasattr(comp["instance"], "startup"):
                    if not comp["instance"].startup():
                        return False
                comp["state"] = ComponentState.RUNNING
            self.state = "running"
            logger.info("System started")
            return True

    def shutdown(self) -> bool:
        with self.lock:
            for _name, comp in self.components.items():
                if hasattr(comp["instance"], "shutdown"):
                    comp["instance"].shutdown()
                comp["state"] = ComponentState.STOPPED
            self.state = "stopped"
            return True
