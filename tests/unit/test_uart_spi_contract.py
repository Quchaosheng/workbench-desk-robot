import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hardware" / "linux_drivers"))

from uart_spi import (
    FakeTransport,
    FrameCrcError,
    FrameFormatError,
    SequenceError,
    TransportBackpressure,
    TransportClosed,
    TransportKind,
    UartSpiFrame,
    UartSpiSession,
)


def session(
    kind: TransportKind = TransportKind.UART, **transport_options: object
) -> tuple[UartSpiSession, FakeTransport]:
    transport = FakeTransport(**transport_options)
    current = UartSpiSession(transport, kind, read_chunk_bytes=7)
    current.open()
    return current, transport


@pytest.mark.parametrize("kind", [TransportKind.UART, TransportKind.SPI])
def test_frame_round_trip_preserves_transport_sequence_and_payload(kind: TransportKind) -> None:
    frame = UartSpiFrame(kind, 42, b"status")

    decoded = UartSpiFrame.decode(frame.encode(), expected_transport=kind)

    assert decoded == frame


def test_frame_rejects_crc_version_length_and_transport_errors() -> None:
    valid = UartSpiFrame(TransportKind.UART, 1, b"hello").encode()
    corrupted = valid[:-1] + bytes([valid[-1] ^ 0xFF])
    with pytest.raises(FrameCrcError):
        UartSpiFrame.decode(corrupted)

    wrong_version = valid[:2] + bytes([2]) + valid[3:]
    with pytest.raises(FrameFormatError, match="version"):
        UartSpiFrame.decode(wrong_version)

    with pytest.raises(FrameFormatError, match="length"):
        UartSpiFrame.decode(valid[:-1])

    with pytest.raises(FrameFormatError, match="does not match"):
        UartSpiFrame.decode(valid, expected_transport=TransportKind.SPI)


def test_frame_rejects_mutable_or_oversized_payload() -> None:
    with pytest.raises(FrameFormatError, match="immutable"):
        UartSpiFrame(TransportKind.UART, 1, bytearray(b"bad"))
    with pytest.raises(FrameFormatError, match="256"):
        UartSpiFrame(TransportKind.UART, 1, b"x" * 257)


def test_session_reassembles_partial_writes_and_reads() -> None:
    current, transport = session(capacity=16, max_write_bytes=3)

    sent = current.send(b"partial", 10)
    received = current.receive()

    assert sent.sequence == received.sequence == 10
    assert received.payload == b"partial"
    assert transport.queued_chunks == 0


def test_session_retries_a_transient_write_failure_with_same_frame() -> None:
    current, _transport = session()
    current.transport.fail_next_write = True

    sent = current.send(b"retry", 11)
    received = current.receive()

    assert sent == received


def test_session_rejects_duplicate_and_stale_sequences() -> None:
    current, transport = session()
    frame = UartSpiFrame(TransportKind.UART, 5, b"one").encode()
    transport.inject_rx(frame)
    assert current.receive().sequence == 5

    transport.inject_rx(frame)
    with pytest.raises(SequenceError, match="duplicate or stale"):
        current.receive()

    transport.inject_rx(UartSpiFrame(TransportKind.UART, 4, b"old").encode())
    with pytest.raises(SequenceError, match="duplicate or stale"):
        current.receive()

    transport.inject_rx(UartSpiFrame(TransportKind.UART, 0x8005, b"ambiguous").encode())
    with pytest.raises(SequenceError, match="duplicate or stale"):
        current.receive()


def test_session_accepts_sequence_wrap_inside_half_range() -> None:
    current, transport = session(TransportKind.SPI)
    transport.inject_rx(UartSpiFrame(TransportKind.SPI, 0xFFFF, b"last").encode())
    assert current.receive().sequence == 0xFFFF
    transport.inject_rx(UartSpiFrame(TransportKind.SPI, 0, b"wrap").encode())
    assert current.receive().sequence == 0


def test_transport_backpressure_and_closed_state_are_explicit() -> None:
    transport = FakeTransport(capacity=1)
    transport.open()
    transport.write(b"one", timeout_s=0)
    with pytest.raises(TransportBackpressure):
        transport.write(b"two", timeout_s=0)
    transport.close()
    with pytest.raises(TransportClosed):
        transport.write(b"closed", timeout_s=0)


def test_session_bounds_retry_budget_and_rejects_wrong_transport() -> None:
    transport = FakeTransport()
    with pytest.raises(ValueError, match="between 0 and 3"):
        UartSpiSession(transport, TransportKind.UART, max_retries=4)

    current, transport = session(TransportKind.UART)
    transport.inject_rx(UartSpiFrame(TransportKind.SPI, 1, b"wrong").encode())
    with pytest.raises(FrameFormatError, match="does not match"):
        current.receive()
