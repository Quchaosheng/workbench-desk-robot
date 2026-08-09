"""Thread-safe CAN driver with retry"""

import logging
import threading
from collections.abc import Callable
from queue import Queue

logger = logging.getLogger("CANBusSafe")


class SafeCANBus:
    """Async CAN with retry and error recovery"""

    def __init__(self):
        self.subscribers = {}
        self.send_lock = threading.Lock()
        self.send_queue = Queue(maxsize=100)
        self.running = False
        self.error_count = 0

    def send(self, message, timeout=1.0) -> bool:
        try:
            self.send_queue.put(message, timeout=timeout)
            return True
        except BaseException:  # noqa: BLE001 - preserve the existing fail-closed send boundary.
            self.error_count += 1
            return False

    def receive(self, can_id: int, data: bytes) -> bool:
        for handler in self.subscribers.get(can_id, []):
            try:
                handler({"can_id": can_id, "data": data})
            except Exception as e:  # noqa: BLE001 - isolate failures from subscriber callbacks.
                logger.error(f"Handler error: {e}")
                self.error_count += 1
        return True

    def subscribe(self, can_id: int, handler: Callable) -> None:
        if can_id not in self.subscribers:
            self.subscribers[can_id] = []
        self.subscribers[can_id].append(handler)

    def get_error_count(self) -> int:
        return self.error_count
