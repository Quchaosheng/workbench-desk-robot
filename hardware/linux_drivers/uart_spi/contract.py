"""Bounded UART/SPI framing contract for software adapter tests."""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Protocol

MAGIC = b"WB"
PROTOCOL_VERSION = 1
MAX_PAYLOAD_BYTES = 256
HEADER = struct.Struct(">2sBBHH")
CRC = struct.Struct(">H")
MAX_FRAME_BYTES = HEADER.size + MAX_PAYLOAD_BYTES + CRC.size


class FrameError(ValueError):
    """Base class for malformed or unsupported frames."""


class FrameFormatError(FrameError):
    """The frame shape, header or bounds are invalid."""


class FrameCrcError(FrameError):
    """The frame payload was corrupted in transit."""


class SequenceError(FrameError):
    """An inbound frame is duplicate, stale or ambiguous."""


class TransportClosed(ConnectionError):
    """The transport is not open."""


class TransportBackpressure(TimeoutError):
    """The bounded transport queue is full."""


class TransportIOError(ConnectionError):
    """The fake transport injected an I/O failure."""


class TransportKind(IntEnum):
    UART = 1
    SPI = 2


def crc16_ccitt(data: bytes, initial: int = 0xFFFF) -> int:
    """Return CRC-16/CCITT-FALSE for one bounded frame."""
    crc = initial
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


@dataclass(frozen=True, slots=True)
class UartSpiFrame:
    """A complete framed payload owned by one UART or SPI endpoint."""

    transport: TransportKind
    sequence: int
    payload: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.transport, TransportKind):
            raise FrameFormatError("transport must be UART or SPI")
        if type(self.sequence) is not int or not 0 <= self.sequence <= 0xFFFF:
            raise FrameFormatError("sequence must be an unsigned 16-bit integer")
        if not isinstance(self.payload, bytes):
            raise FrameFormatError("payload must be immutable bytes")
        if len(self.payload) > MAX_PAYLOAD_BYTES:
            raise FrameFormatError(f"payload exceeds {MAX_PAYLOAD_BYTES} bytes")

    def encode(self) -> bytes:
        header = HEADER.pack(MAGIC, PROTOCOL_VERSION, int(self.transport), self.sequence, len(self.payload))
        body = header + self.payload
        return body + CRC.pack(crc16_ccitt(body))

    @classmethod
    def decode(cls, raw: bytes, *, expected_transport: TransportKind | None = None) -> "UartSpiFrame":
        if not isinstance(raw, bytes) or len(raw) < HEADER.size + CRC.size:
            raise FrameFormatError("frame is shorter than the minimum header and CRC")
        if len(raw) > MAX_FRAME_BYTES:
            raise FrameFormatError("frame exceeds the maximum bounded size")
        magic, version, kind, sequence, payload_length = HEADER.unpack(raw[: HEADER.size])
        if magic != MAGIC:
            raise FrameFormatError("invalid frame magic")
        if version != PROTOCOL_VERSION:
            raise FrameFormatError(f"unsupported protocol version: {version}")
        try:
            transport = TransportKind(kind)
        except ValueError as exc:
            raise FrameFormatError(f"unsupported transport kind: {kind}") from exc
        if expected_transport is not None and transport is not expected_transport:
            raise FrameFormatError("frame transport does not match the endpoint")
        if payload_length > MAX_PAYLOAD_BYTES:
            raise FrameFormatError("payload length exceeds the bounded maximum")
        expected_length = HEADER.size + payload_length + CRC.size
        if len(raw) != expected_length:
            raise FrameFormatError("frame length does not match its payload length")
        if CRC.unpack(raw[-CRC.size :])[0] != crc16_ccitt(raw[:-CRC.size]):
            raise FrameCrcError("frame CRC does not match payload")
        return cls(transport, sequence, raw[HEADER.size : HEADER.size + payload_length])


class TransportPort(Protocol):
    def open(self) -> None: ...

    def close(self) -> None: ...

    def write(self, data: bytes, timeout_s: float) -> int: ...

    def read(self, max_bytes: int, timeout_s: float) -> bytes: ...


def _is_newer(sequence: int, previous: int) -> bool:
    delta = (sequence - previous) & 0xFFFF
    return 0 < delta <= 0x7FFF


class UartSpiSession:
    """Bounded framed I/O session over an injected UART/SPI transport."""

    def __init__(
        self,
        transport: TransportPort,
        kind: TransportKind,
        *,
        max_retries: int = 1,
        read_chunk_bytes: int = 64,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(max_retries) is not int or not 0 <= max_retries <= 3:
            raise ValueError("max_retries must be between 0 and 3")
        if type(read_chunk_bytes) is not int or not 1 <= read_chunk_bytes <= MAX_FRAME_BYTES:
            raise ValueError("read_chunk_bytes is outside the bounded range")
        if not isinstance(kind, TransportKind):
            raise ValueError("kind must be UART or SPI")
        self.transport = transport
        self.kind = kind
        self.max_retries = max_retries
        self.read_chunk_bytes = read_chunk_bytes
        self.clock = clock
        self._rx_buffer = bytearray()
        self._last_rx_sequence: int | None = None

    def open(self) -> None:
        self.transport.open()

    def close(self) -> None:
        self.transport.close()

    def send(self, payload: bytes, sequence: int, *, timeout_s: float = 1.0) -> UartSpiFrame:
        frame = UartSpiFrame(self.kind, sequence, payload)
        encoded = frame.encode()
        last_error: Exception | None = None
        for _attempt in range(self.max_retries + 1):
            offset = 0
            try:
                while offset < len(encoded):
                    written = self.transport.write(encoded[offset:], timeout_s)
                    if type(written) is not int or not 0 < written <= len(encoded) - offset:
                        raise TransportIOError("transport returned an invalid write length")
                    offset += written
                return frame
            except (TransportBackpressure, TransportClosed, TransportIOError) as exc:
                if offset:
                    raise TransportIOError("partial write failed; retry is unsafe") from exc
                last_error = exc
        assert last_error is not None
        raise last_error

    def receive(self, *, timeout_s: float = 1.0) -> UartSpiFrame:
        deadline = self.clock() + timeout_s
        while True:
            frame = self._take_frame_from_buffer()
            if frame is not None:
                if self._last_rx_sequence is not None and not _is_newer(frame.sequence, self._last_rx_sequence):
                    raise SequenceError(
                        f"sequence {frame.sequence} is duplicate or stale after {self._last_rx_sequence}"
                    )
                self._last_rx_sequence = frame.sequence
                return frame
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for a complete UART/SPI frame")
            chunk = self.transport.read(self.read_chunk_bytes, remaining)
            if not chunk:
                raise TimeoutError("transport returned no data before the deadline")
            self._rx_buffer.extend(chunk)
            if len(self._rx_buffer) > MAX_FRAME_BYTES:
                raise FrameFormatError("receive buffer exceeded the bounded frame size")

    def _take_frame_from_buffer(self) -> UartSpiFrame | None:
        if len(self._rx_buffer) < HEADER.size:
            return None
        payload_length = HEADER.unpack(self._rx_buffer[: HEADER.size])[-1]
        if payload_length > MAX_PAYLOAD_BYTES:
            raise FrameFormatError("payload length exceeds the maximum")
        frame_length = HEADER.size + payload_length + CRC.size
        if len(self._rx_buffer) < frame_length:
            return None
        raw = bytes(self._rx_buffer[:frame_length])
        del self._rx_buffer[:frame_length]
        return UartSpiFrame.decode(raw, expected_transport=self.kind)
