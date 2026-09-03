"""Software-only UART/SPI framing contract and deterministic fake transport."""

from .contract import (
    MAX_PAYLOAD_BYTES,
    FrameCrcError,
    FrameError,
    FrameFormatError,
    SequenceError,
    TransportBackpressure,
    TransportClosed,
    TransportIOError,
    TransportKind,
    UartSpiFrame,
    UartSpiSession,
    crc16_ccitt,
)
from .fake_transport import FakeTransport

__all__ = [
    "MAX_PAYLOAD_BYTES",
    "FakeTransport",
    "FrameCrcError",
    "FrameError",
    "FrameFormatError",
    "SequenceError",
    "TransportBackpressure",
    "TransportClosed",
    "TransportIOError",
    "TransportKind",
    "UartSpiFrame",
    "UartSpiSession",
    "crc16_ccitt",
]
