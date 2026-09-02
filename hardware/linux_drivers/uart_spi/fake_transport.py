"""Deterministic bounded fake UART/SPI transport for contract tests."""

from __future__ import annotations

from collections import deque

from .contract import TransportBackpressure, TransportClosed, TransportIOError


class FakeTransport:
    """Loopback transport with bounded queues and injectable failures."""

    def __init__(self, *, capacity: int = 4, max_write_bytes: int | None = None) -> None:
        if type(capacity) is not int or not 1 <= capacity <= 64:
            raise ValueError("capacity must be between 1 and 64")
        if max_write_bytes is not None and (type(max_write_bytes) is not int or max_write_bytes < 1):
            raise ValueError("max_write_bytes must be positive")
        self.capacity = capacity
        self.max_write_bytes = max_write_bytes
        self._chunks: deque[bytes] = deque()
        self.opened = False
        self.fail_next_write = False
        self.fail_next_read = False

    @property
    def queued_chunks(self) -> int:
        return len(self._chunks)

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def write(self, data: bytes, timeout_s: float) -> int:
        del timeout_s
        self._ensure_open()
        if self.fail_next_write:
            self.fail_next_write = False
            raise TransportIOError("injected write failure")
        if not data:
            raise TransportIOError("empty writes are not valid")
        if len(self._chunks) >= self.capacity:
            raise TransportBackpressure("fake transport queue is full")
        count = min(len(data), self.max_write_bytes or len(data))
        self._chunks.append(bytes(data[:count]))
        return count

    def read(self, max_bytes: int, timeout_s: float) -> bytes:
        del timeout_s
        self._ensure_open()
        if self.fail_next_read:
            self.fail_next_read = False
            raise TransportIOError("injected read failure")
        if not self._chunks:
            raise TimeoutError("fake transport has no data")
        chunk = self._chunks.popleft()
        if len(chunk) <= max_bytes:
            return chunk
        self._chunks.appendleft(chunk[max_bytes:])
        return chunk[:max_bytes]

    def inject_rx(self, data: bytes) -> None:
        self._ensure_open()
        if not isinstance(data, bytes) or not data:
            raise ValueError("injected data must be non-empty bytes")
        if len(self._chunks) >= self.capacity:
            raise TransportBackpressure("fake transport queue is full")
        self._chunks.append(data)

    def _ensure_open(self) -> None:
        if not self.opened:
            raise TransportClosed("fake transport is closed")
