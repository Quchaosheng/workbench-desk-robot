"""Standard-library SocketCAN transport for the bounded CAN runtime.

This module owns one AF_CAN/CAN_RAW file descriptor and no worker, queue or
lifecycle state machine.  ``DeviceRuntime`` remains the owner of those
concerns; :class:`SocketCANTransport` only translates the Linux
``struct can_frame`` boundary into immutable :class:`CanFrame` values.
"""

from __future__ import annotations

import errno
import math
import select
import socket
import struct
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from itertools import islice
from typing import Any

from .can_driver_safe import (
    MCU_CAN_ID_ACK,
    MCU_CAN_ID_STOP_ACK,
    MCU_CAN_ID_TELEMETRY,
    CanFrame,
    CanLinkLostError,
    CanTransportBackpressureError,
    CanTransportError,
    CanTransportFrameError,
)

CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_SFF_MASK = 0x000007FF
CAN_EFF_MASK = 0x1FFFFFFF
CAN_ERR_MASK = 0x1FFFFFFF
CAN_ERR_BUSOFF = 0x00000040
CAN_MAX_DLC = 8
CAN_RAW_FILTER_MAX = 512

CAN_FRAME_STRUCT = struct.Struct("=IB3x8s")
CAN_FILTER_STRUCT = struct.Struct("=II")
CAN_ERR_FILTER_STRUCT = struct.Struct("=I")
RXQ_OVFL_STRUCT = struct.Struct("=I")
CAN_FRAME_SIZE = CAN_FRAME_STRUCT.size
SO_TIMESTAMPNS = getattr(socket, "SO_TIMESTAMPNS", 35)
SCM_TIMESTAMPNS = getattr(socket, "SCM_TIMESTAMPNS", SO_TIMESTAMPNS)
SO_RXQ_OVFL = getattr(socket, "SO_RXQ_OVFL", 40)
SCM_RXQ_OVFL = SO_RXQ_OVFL
CAN_RAW_ERR_FILTER = getattr(socket, "CAN_RAW_ERR_FILTER", 2)
_TIMESPEC_STRUCT = struct.Struct("@ll")
_CAN_FLAG_MASK = CAN_EFF_FLAG | CAN_RTR_FLAG | CAN_ERR_FLAG


class SocketCANError(CanTransportError):
    """A SocketCAN operation failed for an environmental or link reason."""


class SocketCANFrameError(CanTransportFrameError):
    """A raw SocketCAN record is malformed and is rejected before Wire V1 decode."""


@dataclass(frozen=True)
class SocketCANFilter:
    """A typed SocketCAN raw filter.

    ``mask`` applies to the arbitration-id bits.  The frame-kind flags are
    automatically included in the kernel mask so a standard filter cannot
    accidentally consume an extended or RTR frame.  Error frames use
    ``CAN_RAW_ERR_FILTER`` separately: Linux assigns the same bit value to
    ``CAN_ERR_FLAG`` and ``CAN_INV_FILTER`` in ``can_filter.can_id``.
    """

    arbitration_id: int
    mask: int
    is_extended_id: bool = False
    is_remote_frame: bool = False

    def __post_init__(self) -> None:
        if type(self.arbitration_id) is not int or self.arbitration_id < 0:
            raise ValueError("filter arbitration_id must be a non-negative integer")
        if type(self.mask) is not int or self.mask < 0:
            raise ValueError("filter mask must be a non-negative integer")
        for name in ("is_extended_id", "is_remote_frame"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"filter {name} must be a bool")
        maximum = CAN_EFF_MASK if self.is_extended_id else CAN_SFF_MASK
        if self.arbitration_id > maximum or self.mask > maximum:
            raise ValueError("filter arbitration_id and mask exceed the selected CAN id width")

    @property
    def raw_can_id(self) -> int:
        value = self.arbitration_id
        if self.is_extended_id:
            value |= CAN_EFF_FLAG
        if self.is_remote_frame:
            value |= CAN_RTR_FLAG
        return value

    @property
    def raw_can_mask(self) -> int:
        # CAN_ERR_FLAG is also CAN_INV_FILTER in the kernel filter ABI.  It
        # must only be used through CAN_RAW_ERR_FILTER for error frames.
        return self.mask | CAN_EFF_FLAG | CAN_RTR_FLAG

    def pack(self) -> bytes:
        return CAN_FILTER_STRUCT.pack(self.raw_can_id, self.raw_can_mask)


def pack_socketcan_frame(frame: CanFrame) -> bytes:
    """Encode one classic CAN frame using Linux ``struct can_frame`` layout."""

    if not isinstance(frame, CanFrame):
        raise SocketCANFrameError("SocketCAN send requires a CanFrame")
    if not isinstance(frame.data, bytes):
        raise SocketCANFrameError("SocketCAN payload must be immutable bytes")
    if type(frame.is_extended_id) is not bool:
        raise SocketCANFrameError("is_extended_id must be a bool")
    if type(frame.is_remote_frame) is not bool:
        raise SocketCANFrameError("is_remote_frame must be a bool")
    if type(frame.is_error_frame) is not bool:
        raise SocketCANFrameError("is_error_frame must be a bool")
    if frame.is_error_frame and (frame.is_extended_id or frame.is_remote_frame):
        raise SocketCANFrameError("CAN error frames cannot also be extended or remote frames")
    if frame.dlc is not None and (type(frame.dlc) is not int or not 0 <= frame.dlc <= CAN_MAX_DLC):
        raise SocketCANFrameError("CAN DLC must be an integer from 0 through 8")
    dlc = frame.effective_dlc
    if type(dlc) is not int or not 0 <= dlc <= CAN_MAX_DLC:
        raise SocketCANFrameError("CAN DLC must be an integer from 0 through 8")

    maximum = CAN_EFF_MASK if frame.is_extended_id or frame.is_error_frame else CAN_SFF_MASK
    if type(frame.arbitration_id) is not int or not 0 <= frame.arbitration_id <= maximum:
        raise SocketCANFrameError("arbitration_id exceeds the selected CAN id width")
    if frame.is_remote_frame:
        if frame.data:
            raise SocketCANFrameError("remote frames must not carry a payload")
    elif len(frame.data) != dlc:
        raise SocketCANFrameError("CAN payload length must match DLC")

    raw_can_id = frame.arbitration_id
    if frame.is_extended_id:
        raw_can_id |= CAN_EFF_FLAG
    if frame.is_remote_frame:
        raw_can_id |= CAN_RTR_FLAG
    if frame.is_error_frame:
        raw_can_id |= CAN_ERR_FLAG
    if frame.raw_can_id is not None and (type(frame.raw_can_id) is not int or not 0 <= frame.raw_can_id <= 0xFFFFFFFF):
        raise SocketCANFrameError("raw CAN ID must be a 32-bit unsigned integer when present")
    if frame.raw_can_id is not None and frame.raw_can_id != raw_can_id:
        raise SocketCANFrameError("raw CAN ID does not match arbitration ID and frame flags")
    payload = frame.data.ljust(CAN_MAX_DLC, b"\x00")
    return CAN_FRAME_STRUCT.pack(raw_can_id, dlc, payload)


def unpack_socketcan_frame(
    payload: bytes,
    *,
    kernel_timestamp_ns: int | None = None,
    kernel_drop_count: int | None = None,
    observed_monotonic_ts: float | None = None,
    observed_wall_ts: float | None = None,
) -> CanFrame:
    """Decode one complete classic CAN record and preserve its frame flags."""

    if not isinstance(payload, bytes):
        raise SocketCANFrameError("SocketCAN receive payload must be bytes")
    if len(payload) != CAN_FRAME_SIZE:
        if len(payload) > CAN_FRAME_SIZE:
            raise SocketCANFrameError(
                f"unsupported SocketCAN frame layout: expected {CAN_FRAME_SIZE} bytes, got {len(payload)}"
            )
        raise SocketCANFrameError(f"short SocketCAN frame: expected {CAN_FRAME_SIZE} bytes, got {len(payload)}")
    raw_can_id, dlc, raw_data = CAN_FRAME_STRUCT.unpack(payload)
    if dlc > CAN_MAX_DLC:
        raise SocketCANFrameError(f"SocketCAN DLC {dlc} exceeds classic CAN maximum {CAN_MAX_DLC}")

    is_error_frame = bool(raw_can_id & CAN_ERR_FLAG)
    is_extended_id = bool(raw_can_id & CAN_EFF_FLAG)
    is_remote_frame = bool(raw_can_id & CAN_RTR_FLAG)
    if is_error_frame and (is_extended_id or is_remote_frame):
        raise SocketCANFrameError("SocketCAN error records cannot also be extended or remote frames")
    if is_error_frame:
        arbitration_id = raw_can_id & CAN_ERR_MASK
    elif is_extended_id:
        arbitration_id = raw_can_id & CAN_EFF_MASK
    else:
        if raw_can_id & ~(CAN_SFF_MASK | _CAN_FLAG_MASK):
            raise SocketCANFrameError("standard SocketCAN record contains out-of-range CAN ID bits")
        arbitration_id = raw_can_id & CAN_SFF_MASK
    data = b"" if is_remote_frame else bytes(raw_data[:dlc])
    if kernel_timestamp_ns is not None and (type(kernel_timestamp_ns) is not int or kernel_timestamp_ns < 0):
        raise SocketCANFrameError("kernel timestamp must be a non-negative integer")
    if kernel_drop_count is not None and (
        type(kernel_drop_count) is not int or not 0 <= kernel_drop_count <= 0xFFFFFFFF
    ):
        raise SocketCANFrameError("kernel RX drop count must be a 32-bit unsigned integer")
    for name, value in (
        ("observed_monotonic_ts", observed_monotonic_ts),
        ("observed_wall_ts", observed_wall_ts),
    ):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value)
        ):
            raise SocketCANFrameError(f"{name} must be finite when present")
    return CanFrame(
        arbitration_id=arbitration_id,
        data=data,
        is_extended_id=is_extended_id,
        is_remote_frame=is_remote_frame,
        is_error_frame=is_error_frame,
        dlc=dlc,
        kernel_timestamp_ns=kernel_timestamp_ns,
        kernel_drop_count=kernel_drop_count,
        observed_monotonic_ts=None if observed_monotonic_ts is None else float(observed_monotonic_ts),
        observed_wall_ts=None if observed_wall_ts is None else float(observed_wall_ts),
        raw_can_id=raw_can_id,
    )


class SocketCANTransport:
    """One bounded, synchronous AF_CAN/CAN_RAW transport port.

    Construction is side-effect free.  ``open`` owns exactly one raw socket;
    ``receive`` uses ``poll`` followed by ``recvmsg`` and never creates a
    background worker or an adapter-local queue.  CAN bus restart remains a
    CAN-core/network-admin operation; the optional recovery probe tells the
    adapter that an operator or supervisor has completed that operation.
    """

    def __init__(
        self,
        interface: str,
        *,
        source: str = "socketcan",
        filters: Iterable[SocketCANFilter] | None = None,
        receive_own_messages: bool = False,
        loopback: bool = True,
        receive_buffer_bytes: int = CAN_FRAME_SIZE * 64,
        error_filter: int | None = CAN_ERR_MASK,
        require_kernel_timestamp: bool = True,
        recovery_probe: Callable[[], bool] | None = None,
        socket_factory: Callable[..., Any] = socket.socket,
        poller_factory: Callable[[], Any] | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._interface = _validate_name(interface, "interface")
        self._source = _validate_name(source, "source")
        if filters is None:
            filters = (
                SocketCANFilter(MCU_CAN_ID_ACK, CAN_SFF_MASK),
                SocketCANFilter(MCU_CAN_ID_STOP_ACK, CAN_SFF_MASK),
                SocketCANFilter(MCU_CAN_ID_TELEMETRY, CAN_SFF_MASK),
            )
        try:
            self._filters = tuple(islice(iter(filters), CAN_RAW_FILTER_MAX + 1))
        except TypeError as exc:
            raise TypeError("filters must be an iterable of SocketCANFilter values") from exc
        if len(self._filters) > CAN_RAW_FILTER_MAX:
            raise ValueError(f"filters cannot exceed the Linux CAN_RAW limit of {CAN_RAW_FILTER_MAX}")
        if any(not isinstance(item, SocketCANFilter) for item in self._filters):
            raise TypeError("filters must contain SocketCANFilter values")
        for name, value in (("receive_own_messages", receive_own_messages), ("loopback", loopback)):
            if type(value) is not bool:
                raise TypeError(f"{name} must be a bool")
        if type(receive_buffer_bytes) is not int or receive_buffer_bytes < CAN_FRAME_SIZE:
            raise ValueError(f"receive_buffer_bytes must be at least {CAN_FRAME_SIZE} bytes")
        if error_filter is not None and (type(error_filter) is not int or not 0 <= error_filter <= CAN_ERR_MASK):
            raise ValueError("error_filter must be a 29-bit mask when present")
        if type(require_kernel_timestamp) is not bool:
            raise TypeError("require_kernel_timestamp must be a bool")
        if recovery_probe is not None and not callable(recovery_probe):
            raise TypeError("recovery_probe must be callable when present")
        if not callable(socket_factory):
            raise TypeError("socket_factory must be callable")
        if poller_factory is not None and not callable(poller_factory):
            raise TypeError("poller_factory must be callable when present")
        if not callable(monotonic_clock) or not callable(wall_clock):
            raise TypeError("clock arguments must be callable")
        self._receive_own_messages = receive_own_messages
        self._loopback = loopback
        self._receive_buffer_bytes = receive_buffer_bytes
        self._error_filter = error_filter
        self._require_kernel_timestamp = require_kernel_timestamp
        self._recovery_probe = recovery_probe
        self._socket_factory = socket_factory
        self._poller_factory = poller_factory
        self._monotonic_clock = monotonic_clock
        self._wall_clock = wall_clock
        self._lock = threading.RLock()
        self._socket: Any | None = None

    @property
    def interface(self) -> str:
        return self._interface

    @property
    def source(self) -> str:
        return self._source

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._socket is not None

    def open(self) -> None:
        with self._lock:
            if self._socket is not None:
                return
            if not hasattr(socket, "AF_CAN") or not hasattr(socket, "CAN_RAW"):
                raise SocketCANError("this platform does not expose AF_CAN/CAN_RAW")
            _resolve_poll_api(self._poller_factory)
            candidate = None
            try:
                candidate = self._socket_factory(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
                candidate.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self._receive_buffer_bytes)
                candidate.setsockopt(socket.SOL_SOCKET, SO_RXQ_OVFL, 1)
                candidate.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_LOOPBACK, int(self._loopback))
                candidate.setsockopt(
                    socket.SOL_CAN_RAW,
                    socket.CAN_RAW_RECV_OWN_MSGS,
                    int(self._receive_own_messages),
                )
                candidate.setsockopt(
                    socket.SOL_CAN_RAW,
                    socket.CAN_RAW_FILTER,
                    b"".join(item.pack() for item in self._filters),
                )
                if self._error_filter is not None:
                    candidate.setsockopt(
                        socket.SOL_CAN_RAW,
                        CAN_RAW_ERR_FILTER,
                        CAN_ERR_FILTER_STRUCT.pack(self._error_filter),
                    )
                if self._require_kernel_timestamp:
                    candidate.setsockopt(socket.SOL_SOCKET, SO_TIMESTAMPNS, 1)
                candidate.bind((self._interface,))
                candidate.setblocking(False)
            except (AttributeError, OSError, TypeError, ValueError) as exc:
                try:
                    if candidate is not None:
                        candidate.close()
                except (AttributeError, OSError):
                    pass
                raise SocketCANError(f"failed to open SocketCAN interface {self._interface!r}: {exc}") from exc
            self._socket = candidate

    def close(self) -> None:
        with self._lock:
            candidate = self._socket
            self._socket = None
        if candidate is None:
            return
        try:
            candidate.close()
        except (AttributeError, OSError) as exc:
            raise SocketCANError(f"failed to close SocketCAN interface {self._interface!r}: {exc}") from exc

    def send(self, frame: CanFrame) -> None:
        payload = pack_socketcan_frame(frame)
        candidate = self._require_socket()
        try:
            sent = candidate.send(payload)
        except OSError as exc:
            raise _map_socket_error(exc, operation="send") from exc
        if sent != len(payload):
            raise SocketCANError(f"SocketCAN short write: expected {len(payload)} bytes, sent {sent}")

    def receive(self, timeout_s: float) -> CanFrame | None:
        if (
            isinstance(timeout_s, bool)
            or not isinstance(timeout_s, int | float)
            or not math.isfinite(timeout_s)
            or timeout_s < 0
        ):
            raise ValueError("timeout_s must be a finite non-negative number")
        candidate = self._require_socket()
        poller_factory, poll_input_mask, poll_error_mask = _resolve_poll_api(self._poller_factory)
        poller = poller_factory()
        try:
            poller.register(candidate, poll_input_mask | poll_error_mask)
            events = poller.poll(min(math.ceil(float(timeout_s) * 1000), 2_147_483_647))
        except OSError as exc:
            raise _map_socket_error(exc, operation="poll") from exc
        except (AttributeError, TypeError, ValueError) as exc:
            raise SocketCANError(f"SocketCAN poll failed: {exc}") from exc
        if not events:
            return None
        event_mask = 0
        candidate_fd = _socket_fileno(candidate)
        for event in events:
            if not isinstance(event, tuple) or len(event) != 2:
                raise SocketCANError("SocketCAN poll returned an invalid event record")
            file_descriptor, mask = event
            if type(file_descriptor) is not int or type(mask) is not int:
                raise SocketCANError("SocketCAN poll returned invalid descriptor or event mask")
            if candidate_fd is not None and file_descriptor != candidate_fd:
                continue
            if mask < 0:
                raise SocketCANError("SocketCAN poll returned an invalid event mask")
            event_mask |= mask
        if not event_mask & poll_input_mask:
            if event_mask & poll_error_mask:
                raise CanLinkLostError(f"SocketCAN interface {self._interface!r} reported poll error 0x{event_mask:x}")
            return None

        try:
            received = candidate.recvmsg(CAN_FRAME_SIZE, 256)
        except BlockingIOError:
            return None
        except OSError as exc:
            if exc.errno in {errno.EAGAIN, errno.EWOULDBLOCK}:
                return None
            raise _map_socket_error(exc, operation="receive") from exc
        if not isinstance(received, tuple) or len(received) != 4:
            raise SocketCANFrameError("SocketCAN recvmsg returned an invalid record shape")
        raw, ancillary, message_flags, _address = received
        if not isinstance(raw, bytes):
            raise SocketCANFrameError("SocketCAN receive payload must be bytes")
        if not isinstance(message_flags, int):
            raise SocketCANFrameError("SocketCAN recvmsg returned an invalid message flag set")
        if message_flags & (getattr(socket, "MSG_TRUNC", 0) | getattr(socket, "MSG_CTRUNC", 0)):
            raise SocketCANFrameError("SocketCAN receive record was truncated")
        if message_flags & getattr(socket, "MSG_ERRQUEUE", 0):
            raise SocketCANFrameError("SocketCAN receive returned an error-queue record")
        kernel_timestamp_ns, kernel_drop_count = _extract_ancillary_metadata(ancillary)
        if self._require_kernel_timestamp and kernel_timestamp_ns is None:
            raise SocketCANFrameError("SocketCAN receive record did not contain SO_TIMESTAMPNS")
        observed_monotonic_ts = _read_clock(self._monotonic_clock, "monotonic")
        observed_wall_ts = _read_clock(self._wall_clock, "wall")
        return unpack_socketcan_frame(
            raw,
            kernel_timestamp_ns=kernel_timestamp_ns,
            kernel_drop_count=kernel_drop_count,
            observed_monotonic_ts=observed_monotonic_ts,
            observed_wall_ts=observed_wall_ts,
        )

    def recover(self) -> bool:
        """Acknowledge an externally completed CAN-core restart, if configured."""

        if not self.is_open or self._recovery_probe is None:
            return False
        try:
            result = self._recovery_probe()
            if type(result) is not bool:
                raise TypeError("SocketCAN recovery probe must return bool")
            return result
        except Exception as exc:
            raise SocketCANError(f"SocketCAN recovery probe failed: {exc}") from exc

    def __enter__(self) -> SocketCANTransport:
        self.open()
        return self

    def __exit__(self, _exc_type: object, _exc_value: object, _traceback: object) -> None:
        self.close()

    def _require_socket(self) -> Any:
        with self._lock:
            if self._socket is None:
                raise CanLinkLostError(f"SocketCAN interface {self._interface!r} is not open")
            return self._socket


def _validate_name(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be a non-empty, trimmed string without NUL")
    return value


def _resolve_poll_api(poller_factory: Callable[[], Any] | None) -> tuple[Callable[[], Any], int, int]:
    resolved_factory = poller_factory if poller_factory is not None else getattr(select, "poll", None)
    poll_input_mask = getattr(select, "POLLIN", None)
    poll_error_masks = tuple(getattr(select, name, None) for name in ("POLLERR", "POLLHUP", "POLLNVAL"))
    if (
        not callable(resolved_factory)
        or type(poll_input_mask) is not int
        or any(type(mask) is not int for mask in poll_error_masks)
    ):
        raise SocketCANError("this platform does not expose select.poll SocketCAN support")
    return resolved_factory, poll_input_mask, poll_error_masks[0] | poll_error_masks[1] | poll_error_masks[2]


def _socket_fileno(candidate: Any) -> int | None:
    try:
        value = candidate.fileno()
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    return value if type(value) is int else None


def _read_clock(clock: Callable[[], float], name: str) -> float:
    try:
        value = clock()
    except Exception as exc:
        raise SocketCANFrameError(f"{name} clock failed: {exc}") from exc
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise SocketCANFrameError(f"{name} clock returned a non-finite value")
    return float(value)


def _extract_ancillary_metadata(ancillary: object) -> tuple[int | None, int | None]:
    if not isinstance(ancillary, list | tuple):
        raise SocketCANFrameError("SocketCAN ancillary data has an invalid shape")
    timestamp: int | None = None
    kernel_drop_count: int | None = None
    for item in ancillary:
        if not isinstance(item, tuple) or len(item) != 3:
            raise SocketCANFrameError("SocketCAN ancillary record has an invalid shape")
        level, cmsg_type, data = item
        if level != socket.SOL_SOCKET:
            continue
        if cmsg_type in {SO_TIMESTAMPNS, SCM_TIMESTAMPNS}:
            if timestamp is not None:
                raise SocketCANFrameError("SocketCAN receive record contained duplicate timestamps")
            if not isinstance(data, bytes) or len(data) < _TIMESPEC_STRUCT.size:
                raise SocketCANFrameError("SocketCAN SO_TIMESTAMPNS ancillary data is truncated")
            seconds, nanoseconds = _TIMESPEC_STRUCT.unpack(data[: _TIMESPEC_STRUCT.size])
            if not 0 <= nanoseconds < 1_000_000_000:
                raise SocketCANFrameError("SocketCAN kernel timestamp has an invalid nanosecond field")
            timestamp = seconds * 1_000_000_000 + nanoseconds
            if timestamp < 0:
                raise SocketCANFrameError("SocketCAN kernel timestamp must be non-negative")
        elif cmsg_type in {SO_RXQ_OVFL, SCM_RXQ_OVFL}:
            if kernel_drop_count is not None:
                raise SocketCANFrameError("SocketCAN receive record contained duplicate RX drop counters")
            if not isinstance(data, bytes) or len(data) < RXQ_OVFL_STRUCT.size:
                raise SocketCANFrameError("SocketCAN SO_RXQ_OVFL ancillary data is truncated")
            (kernel_drop_count,) = RXQ_OVFL_STRUCT.unpack(data[: RXQ_OVFL_STRUCT.size])
    return timestamp, kernel_drop_count


def _map_socket_error(error: OSError, *, operation: str) -> CanTransportError:
    if error.errno in {errno.EAGAIN, errno.EWOULDBLOCK, errno.ENOBUFS}:
        return CanTransportBackpressureError(f"SocketCAN {operation} temporarily backpressured: {error}")
    if error.errno in {
        errno.EBADF,
        errno.EHOSTDOWN,
        errno.EHOSTUNREACH,
        errno.EIO,
        errno.ENETDOWN,
        errno.ENETRESET,
        errno.ENODEV,
        errno.ENETUNREACH,
        errno.ENXIO,
        errno.ENOTCONN,
        errno.ENOLINK,
        errno.EPIPE,
        errno.ESHUTDOWN,
    }:
        return CanLinkLostError(f"SocketCAN {operation} lost the interface: {error}")
    return SocketCANError(f"SocketCAN {operation} failed: {error}")
