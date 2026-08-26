"""Bounded host-side CAN adapter hosted by the unified device runtime."""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import IntEnum, StrEnum
from typing import Protocol

logger = logging.getLogger("CANBusSafe")

MCU_WIRE_VERSION_V1 = 0x10
MCU_WIRE_DLC = 8
MCU_CAN_ID_STOP = 0x080
MCU_CAN_ID_STOP_ACK = 0x081
MCU_CAN_ID_COMMAND = 0x100
MCU_CAN_ID_ACK = 0x101
MCU_CAN_ID_TELEMETRY = 0x180


class CanFrameKind(StrEnum):
    COMMAND = "command"
    ACK = "ack"
    TELEMETRY = "telemetry"
    STOP = "stop"
    STOP_ACK = "stop_ack"


class CanLinkState(StrEnum):
    NEW = "new"
    STARTING = "starting"
    ACTIVE = "active"
    STOPPING = "stopping"
    SAFE_STOPPED = "safe_stopped"
    BUS_OFF = "bus_off"
    LINK_LOST = "link_lost"
    SHUTDOWN = "shutdown"


class DeviceRuntimeState(StrEnum):
    """Lifecycle states owned by :class:`DeviceRuntime`.

    CAN link health is deliberately represented separately by ``CanLinkState``.
    An adapter must not use its link state as a second lifecycle owner.
    """

    NEW = "new"
    CONFIGURING = "configuring"
    CONFIGURED = "configured"
    ACTIVATING = "activating"
    ACTIVE = "active"
    DEACTIVATING = "deactivating"
    CLEANED = "cleaned"
    FAILED = "failed"


class CanSendStatus(StrEnum):
    QUEUED = "queued"
    BACKPRESSURE = "backpressure"
    INVALID_FRAME = "invalid_frame"
    CORRELATION_CONFLICT = "correlation_conflict"
    NOT_RUNNING = "not_running"
    LINK_UNAVAILABLE = "link_unavailable"


class CanReceiveStatus(StrEnum):
    ACCEPTED = "accepted"
    INVALID_FRAME = "invalid_frame"
    DUPLICATE = "duplicate"
    LATE = "late"
    UNCORRELATED = "uncorrelated"


class CanDiagnosticCode(StrEnum):
    INVALID_FRAME = "invalid_frame"
    BACKPRESSURE = "backpressure"
    CORRELATION_CONFLICT = "correlation_conflict"
    ACK_TIMEOUT = "ack_timeout"
    STOP_TIMEOUT = "stop_timeout"
    STOP_REJECTED = "stop_rejected"
    BUS_OFF = "bus_off"
    LINK_LOST = "link_lost"
    DUPLICATE_ACK = "duplicate_ack"
    LATE_ACK = "late_ack"
    UNCORRELATED_ACK = "uncorrelated_ack"
    COMMAND_REJECTED = "command_rejected"
    DUPLICATE_TELEMETRY = "duplicate_telemetry"
    STALE_TELEMETRY = "stale_telemetry"
    CLOCK_ROLLBACK = "clock_rollback"
    SUBSCRIBER_ERROR = "subscriber_error"
    STOP_PREEMPTED = "stop_preempted"
    SHUTDOWN_TIMEOUT = "shutdown_timeout"


class _WireOpcode(IntEnum):
    RESERVED = 0
    MOVE = 1
    GRIP_OPEN = 2
    GRIP_CLOSE = 3
    HOLD = 4
    STOP = 5
    HEARTBEAT = 6


class _WireResult(IntEnum):
    ACCEPTED = 0
    REJECTED = 1


class _WireFault(IntEnum):
    NONE = 0
    ACK_TIMEOUT = 1
    STOP_TIMEOUT = 2
    STOP_REJECTED = 3
    LINK_LOST = 4
    DUPLICATE_FRAME = 5
    WATCHDOG_EXPIRED = 6
    MALFORMED_FRAME = 7


class _WireMode(IntEnum):
    IDLE = 0
    MOVING = 1
    HOLDING = 2
    STOPPED = 3
    FAULTED = 4


_ID_TO_KIND = {
    MCU_CAN_ID_COMMAND: CanFrameKind.COMMAND,
    MCU_CAN_ID_ACK: CanFrameKind.ACK,
    MCU_CAN_ID_TELEMETRY: CanFrameKind.TELEMETRY,
    MCU_CAN_ID_STOP: CanFrameKind.STOP,
    MCU_CAN_ID_STOP_ACK: CanFrameKind.STOP_ACK,
}
_ORDINARY_OPCODES = frozenset(
    {
        _WireOpcode.MOVE,
        _WireOpcode.GRIP_OPEN,
        _WireOpcode.GRIP_CLOSE,
        _WireOpcode.HOLD,
        _WireOpcode.HEARTBEAT,
    }
)
_INBOUND_KINDS = frozenset({CanFrameKind.ACK, CanFrameKind.STOP_ACK, CanFrameKind.TELEMETRY})
_OUTBOUND_KINDS = frozenset({CanFrameKind.COMMAND, CanFrameKind.STOP})


class CanFrameValidationError(ValueError):
    pass


class CanTransportError(Exception):
    """Base exception exposed by an injected transport port."""


class CanBusOffError(CanTransportError):
    pass


class CanLinkLostError(CanTransportError):
    pass


@dataclass(frozen=True)
class CanFrame:
    arbitration_id: int
    data: bytes
    is_extended_id: bool = False
    is_remote_frame: bool = False
    is_error_frame: bool = False


@dataclass(frozen=True)
class CanWireFrame:
    frame: CanFrame
    kind: CanFrameKind
    command_id: int | None = None
    sequence_no: int | None = None
    opcode: int | None = None
    retry_count: int | None = None
    result_code: int | None = None
    fault_code: int | None = None
    device_mode: int | None = None


@dataclass(frozen=True)
class CanTransportConfig:
    queue_capacity: int = 64
    ack_timeout_s: float = 0.100
    ack_retry_budget: int = 2
    stop_timeout_s: float = 0.050
    stop_retry_budget: int = 1
    poll_interval_s: float = 0.010
    shutdown_timeout_s: float = 1.0
    max_subscribers_per_id: int = 16
    diagnostic_capacity: int = 128
    correlation_capacity: int = 128
    initial_stop_command_id: int = 0x8000
    telemetry_capacity: int = 64
    health_capacity: int = 128
    source: str = "mcu-can"
    interface: str = "injected-can"

    def __post_init__(self) -> None:
        for name in (
            "queue_capacity",
            "telemetry_capacity",
            "health_capacity",
            "max_subscribers_per_id",
            "correlation_capacity",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("ack_retry_budget", "stop_retry_budget"):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 255:
                raise ValueError(f"{name} must be an integer from 0 through 255")
        for name in ("ack_timeout_s", "stop_timeout_s", "poll_interval_s", "shutdown_timeout_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"{name} must be a finite positive number")
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a finite positive number")
        if type(self.initial_stop_command_id) is not int or not 0x8000 <= self.initial_stop_command_id <= 0xFFFF:
            raise ValueError("initial_stop_command_id must be in the STOP command partition")
        if type(self.diagnostic_capacity) is not int or self.diagnostic_capacity <= 0:
            raise ValueError("diagnostic_capacity must be a positive integer")
        for name in ("source", "interface"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True)
class CanSendResult:
    status: CanSendStatus
    reason: str | None = None
    command_id: int | None = None

    @property
    def accepted(self) -> bool:
        return self.status is CanSendStatus.QUEUED


@dataclass(frozen=True)
class CanReceiveResult:
    status: CanReceiveStatus
    wire_frame: CanWireFrame | None = None
    confirmed: bool = False
    callback_errors: int = 0
    reason: str | None = None
    envelope: CanTransportEnvelope | None = None


@dataclass(frozen=True)
class CanDiagnostic:
    code: CanDiagnosticCode
    observed_at: float
    detail: str
    command_id: int | None = None


@dataclass(frozen=True)
class CanTransportEnvelope:
    """Immutable ingress metadata for the future typed runtime boundary."""

    source: str
    interface: str
    sequence: int
    monotonic_ts: float
    wall_ts: float
    health: CanLinkState
    wire_frame: CanWireFrame
    evidence_refs: tuple[str, ...] = ()


class MonotonicClock(Protocol):
    def monotonic(self) -> float: ...


class CanTransportPort(Protocol):
    def open(self) -> None: ...

    def send(self, frame: CanFrame) -> None: ...

    def receive(self, timeout_s: float) -> CanFrame | None: ...

    def recover(self) -> bool: ...

    def close(self) -> None: ...


class _SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()


@dataclass
class _PendingRequest:
    wire_frame: CanWireFrame
    deadline: float
    retry_budget_used: int
    sent_retry_counts: set[int]


@dataclass(frozen=True)
class _Dispatch:
    wire_frame: CanWireFrame
    is_retry: bool


CorrelationKey = tuple[CanFrameKind, int, int]
Subscriber = Callable[[CanWireFrame], None]


class DeviceAdapter(Protocol):
    """Port implemented by a hardware adapter hosted by ``DeviceRuntime``."""

    def configure(self) -> bool: ...

    def activate(self) -> bool: ...

    def poll(self, receive_timeout_s: float) -> object | None: ...

    def deactivate(self) -> bool: ...

    def cleanup(self) -> bool: ...


class DeviceRuntime:
    """The single lifecycle, worker, queue and callback owner for one device.

    The runtime is transport-neutral at its public boundary.  The CAN adapter
    uses the private command/telemetry/health plane methods while holding this
    one lock; it never creates another worker, cancellation token, lifecycle
    state machine, queue or subscriber registry.
    """

    def __init__(
        self,
        adapter: DeviceAdapter,
        *,
        command_capacity: int,
        telemetry_capacity: int,
        health_capacity: int,
        max_subscribers_per_id: int,
        poll_interval_s: float,
    ) -> None:
        self._validate_capacity(command_capacity, "command_capacity")
        self._validate_capacity(telemetry_capacity, "telemetry_capacity")
        self._validate_capacity(health_capacity, "health_capacity")
        self._validate_capacity(max_subscribers_per_id, "max_subscribers_per_id")
        if (
            isinstance(poll_interval_s, bool)
            or not isinstance(poll_interval_s, int | float)
            or not math.isfinite(poll_interval_s)
            or poll_interval_s <= 0
        ):
            raise ValueError("poll_interval_s must be a finite positive number")

        self._adapter = adapter
        self._command_capacity = command_capacity
        self._telemetry_capacity = telemetry_capacity
        self._health_capacity = health_capacity
        self._max_subscribers_per_id = max_subscribers_per_id
        self._poll_interval_s = float(poll_interval_s)
        self._lock = threading.RLock()
        self._cancel_event = threading.Event()
        self._state = DeviceRuntimeState.NEW
        self._worker: threading.Thread | None = None
        self._lifecycle_operation: str | None = None
        self._active_operations = 0
        self._generation = 0
        self._configured = False
        self._activated = False
        self._cleanup_in_progress = False
        self._cleanup_done = False
        self._shutdown_requested = False
        self._shutdown_result: bool | None = None
        self._shutdown_timeout_reported = False

        # These are the only runtime data planes.  The adapter's protocol
        # state is protected by this same lock, so admission and dispatch are
        # atomic with respect to lifecycle transitions.
        self._command_queue: deque[object] = deque()
        self._telemetry_queue: deque[object] = deque()
        self._health_queue: deque[object] = deque()
        self._telemetry_drop_count = 0
        self._health_drop_count = 0
        self._error_count = 0
        self._subscribers: dict[int, list[Subscriber]] = {}

    @staticmethod
    def _validate_capacity(value: int, name: str) -> None:
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")

    @property
    def lock(self) -> threading.RLock:
        """The shared state lock used by the adapter port."""

        return self._lock

    @property
    def state(self) -> DeviceRuntimeState:
        with self._lock:
            return self._state

    @property
    def command_depth(self) -> int:
        with self._lock:
            return len(self._command_queue)

    @property
    def telemetry_depth(self) -> int:
        with self._lock:
            return len(self._telemetry_queue)

    @property
    def telemetry_drop_count(self) -> int:
        with self._lock:
            return self._telemetry_drop_count

    @property
    def health_drop_count(self) -> int:
        with self._lock:
            return self._health_drop_count

    @property
    def error_count(self) -> int:
        with self._lock:
            return self._error_count

    @property
    def worker_alive(self) -> bool:
        with self._lock:
            return self._worker is not None and self._worker.is_alive()

    def start(self, *, background: bool = True) -> bool:
        """Run configure/activate once and optionally start the one worker."""

        if type(background) is not bool:
            raise ValueError("background must be a bool")
        with self._lock:
            if self._state is not DeviceRuntimeState.NEW:
                return False
            self._state = DeviceRuntimeState.CONFIGURING
            self._lifecycle_operation = "start"
            self._generation += 1
            self._cancel_event.clear()

        try:
            configured = bool(self._adapter.configure())
        except Exception as exc:  # noqa: BLE001 - adapter faults are isolated at the runtime boundary.
            self._notify_adapter_error(exc)
            configured = False

        with self._lock:
            if configured:
                self._configured = True
            if not configured:
                if self._state is not DeviceRuntimeState.DEACTIVATING:
                    self._state = DeviceRuntimeState.FAILED
            elif self._state is DeviceRuntimeState.CONFIGURING:
                self._state = DeviceRuntimeState.CONFIGURED
            else:
                # shutdown() won the race; do not activate an abandoned port.
                configured = False

        if not configured:
            self._finish_start(False)
            return False

        with self._lock:
            if self._state is not DeviceRuntimeState.CONFIGURED:
                activate = False
            else:
                self._state = DeviceRuntimeState.ACTIVATING
                activate = True
        if not activate:
            self._finish_start(False)
            return False

        try:
            activated = bool(self._adapter.activate())
        except Exception as exc:  # noqa: BLE001 - adapter faults are isolated at the runtime boundary.
            self._notify_adapter_error(exc)
            activated = False

        with self._lock:
            self._activated = activated
            accepted = activated and self._state is DeviceRuntimeState.ACTIVATING and not self._shutdown_requested
            if accepted:
                self._state = DeviceRuntimeState.ACTIVE
                self._lifecycle_operation = None
                if background:
                    self._worker = threading.Thread(
                        target=self._worker_main,
                        name="device-runtime-worker",
                        daemon=True,
                    )
                    self._worker.start()
                    return True
                return True

        self._finish_start(activated)
        return False

    def _finish_start(self, activated: bool) -> None:
        """Dispose an activation that failed or lost a shutdown race."""

        with self._lock:
            shutdown_requested = self._shutdown_requested or self._state is DeviceRuntimeState.DEACTIVATING
            self._state = DeviceRuntimeState.DEACTIVATING
            # Keep the lifecycle marker until the owner has completed cleanup.
            # A concurrent shutdown must not mistake this hand-off window for
            # an idle runtime and start a second cleanup owner.
            self._cleanup_in_progress = True
        cleanup_ok = self._run_cleanup(activated)
        with self._lock:
            self._cleanup_in_progress = False
            self._cleanup_done = cleanup_ok
            self._activated = False
            self._worker = None
            self._lifecycle_operation = None
            if shutdown_requested:
                self._state = DeviceRuntimeState.CLEANED if cleanup_ok else DeviceRuntimeState.FAILED
                self._shutdown_result = cleanup_ok
            else:
                self._state = DeviceRuntimeState.FAILED

    def service_once(self, *, receive_timeout_s: float = 0.0) -> object | None:
        """Let the runtime's sole worker, or a manual caller, poll the adapter."""

        if (
            isinstance(receive_timeout_s, bool)
            or not isinstance(receive_timeout_s, int | float)
            or not math.isfinite(receive_timeout_s)
            or receive_timeout_s < 0
        ):
            raise ValueError("receive_timeout_s must be a finite non-negative number")
        with self._lock:
            if self._state is not DeviceRuntimeState.ACTIVE:
                return None
            if self._worker is not None and threading.current_thread() is not self._worker:
                raise RuntimeError("manual service is unavailable while the background worker is active")
        try:
            return self._adapter.poll(float(receive_timeout_s))
        except Exception as exc:  # noqa: BLE001 - an adapter exception fails closed without killing the process.
            self._notify_adapter_error(exc)
            return None

    def shutdown(self, *, timeout_s: float) -> bool:
        """Cancel, join and clean up exactly once.

        ``False`` means a worker or cleanup operation is still outstanding;
        callers may retry.  A terminal ``CLEANED`` runtime returns the stored
        cleanup result instead of treating the state label as success.
        """

        if (
            isinstance(timeout_s, bool)
            or not isinstance(timeout_s, int | float)
            or not math.isfinite(timeout_s)
            or timeout_s < 0
        ):
            raise ValueError("timeout_s must be a finite non-negative number")
        deadline = time.monotonic() + float(timeout_s)
        with self._lock:
            if self._state is DeviceRuntimeState.CLEANED:
                return self._shutdown_result is True
            self._shutdown_requested = True
            self._cancel_event.set()
            self._command_queue.clear()
            self._telemetry_queue.clear()
            if self._state is not DeviceRuntimeState.CLEANED:
                self._state = DeviceRuntimeState.DEACTIVATING
            worker = self._worker

            # The adapter may be in a blocking configure/activate/recovery
            # operation.  It owns that call until it returns; cleanup must not
            # race it.  The operation's completion path calls the finalizer.

        shutdown_hook = getattr(self._adapter, "on_runtime_shutdown_requested", None)
        if shutdown_hook is not None:
            shutdown_hook()

        if worker is not None and worker is not threading.current_thread():
            remaining = max(0.0, deadline - time.monotonic())
            worker.join(remaining)
            if worker.is_alive():
                self._notify_shutdown_timeout()
                return False
        elif worker is threading.current_thread():
            self._notify_shutdown_timeout()
            return False

        with self._lock:
            cleanup_in_progress = self._cleanup_in_progress
            operation_pending = self._lifecycle_operation is not None or self._active_operations > 0
            cleaned = self._state is DeviceRuntimeState.CLEANED
            shutdown_result = self._shutdown_result
        if cleanup_in_progress:
            return False
        if operation_pending:
            # Cancellation has been accepted, but the operation that owns the
            # blocking call has not completed its cleanup yet.  Report failure
            # until a later call observes CLEANED and its stored result.
            return False
        if cleaned:
            return shutdown_result is True
        result = self._finalize_shutdown()
        return result is True

    def _finalize_shutdown(self) -> bool | None:
        with self._lock:
            if self._state is DeviceRuntimeState.CLEANED:
                return self._shutdown_result
            if self._state is not DeviceRuntimeState.DEACTIVATING:
                return False
            if self._worker is not None and self._worker.is_alive():
                return False
            if self._lifecycle_operation is not None or self._active_operations > 0 or self._cleanup_in_progress:
                return None
            self._cleanup_in_progress = True
            activated = self._activated
        cleanup_ok = self._run_cleanup(activated)
        with self._lock:
            self._cleanup_in_progress = False
            self._cleanup_done = cleanup_ok
            self._activated = False
            self._worker = None
            self._state = DeviceRuntimeState.CLEANED if cleanup_ok else DeviceRuntimeState.FAILED
            self._shutdown_result = cleanup_ok
        return cleanup_ok

    def _run_cleanup(self, activated: bool) -> bool:
        deactivate_ok = True
        cleanup_ok = True
        if activated or self._configured:
            try:
                deactivate_ok = bool(self._adapter.deactivate())
            except Exception as exc:  # noqa: BLE001 - cleanup must report failure, not revive the adapter.
                self._notify_adapter_error(exc)
                deactivate_ok = False
        try:
            cleanup_ok = bool(self._adapter.cleanup())
        except Exception as exc:  # noqa: BLE001 - cleanup must report failure, not revive the adapter.
            self._notify_adapter_error(exc)
            cleanup_ok = False
        return deactivate_ok and cleanup_ok

    def begin_operation(self) -> int | None:
        """Reserve a blocking adapter operation against concurrent cleanup."""

        with self._lock:
            if self._state is not DeviceRuntimeState.ACTIVE:
                return None
            self._active_operations += 1
            return self._generation

    def operation_is_current(self, token: int) -> bool:
        with self._lock:
            return self._state is DeviceRuntimeState.ACTIVE and token == self._generation

    def end_operation(self, token: int) -> None:
        del token
        with self._lock:
            if self._active_operations > 0:
                self._active_operations -= 1
            should_finalize = (
                self._shutdown_requested
                and self._state is DeviceRuntimeState.DEACTIVATING
                and self._active_operations == 0
                and self._lifecycle_operation is None
                and (self._worker is None or not self._worker.is_alive())
            )
        if should_finalize:
            self._finalize_shutdown()

    def submit_command(
        self,
        item: object,
        *,
        priority: bool,
        admit: Callable[[], CanSendResult],
        on_priority: Callable[[], None],
        on_backpressure: Callable[[], CanSendResult],
    ) -> CanSendResult:
        """Atomically admit an adapter command into the runtime command plane."""

        with self._lock:
            result = admit()
            if not result.accepted:
                return result
            if not priority and len(self._command_queue) >= self._command_capacity:
                return on_backpressure()
            if priority:
                on_priority()
            self._command_queue.appendleft(item) if priority else self._command_queue.append(item)
            return result

    def _pop_command_locked(self) -> object | None:
        return self._command_queue.popleft() if self._command_queue else None

    def _command_snapshot_locked(self) -> tuple[object, ...]:
        return tuple(self._command_queue)

    def _clear_commands_locked(self) -> None:
        self._command_queue.clear()

    def _enqueue_priority_locked(self, item: object) -> None:
        self._command_queue.clear()
        self._command_queue.appendleft(item)

    def publish_telemetry(self, item: object) -> None:
        """Place one item in the bounded telemetry plane.

        Producers and dispatchers are separate operations even though the CAN
        poll path drains one item immediately after ingress. This keeps the
        capacity and drop policy real for adapters that batch or fan in data.
        """

        with self._lock:
            if len(self._telemetry_queue) >= self._telemetry_capacity:
                self._telemetry_queue.popleft()
                self._telemetry_drop_count += 1
            self._telemetry_queue.append(item)

    def take_telemetry(self) -> object | None:
        with self._lock:
            return self._telemetry_queue.popleft() if self._telemetry_queue else None

    def record_health(self, item: object) -> None:
        with self._lock:
            self._record_health_locked(item)

    def _record_health_locked(self, item: object) -> None:
        if len(self._health_queue) >= self._health_capacity:
            self._health_queue.popleft()
            self._health_drop_count += 1
        self._health_queue.append(item)
        self._error_count += 1

    def health_records(self) -> tuple[object, ...]:
        with self._lock:
            return tuple(self._health_queue)

    def subscribe(self, arbitration_id: int, handler: Subscriber) -> bool:
        with self._lock:
            handlers = self._subscribers.setdefault(arbitration_id, [])
            if any(existing is handler for existing in handlers):
                return False
            if len(handlers) >= self._max_subscribers_per_id:
                return False
            handlers.append(handler)
            return True

    def unsubscribe(self, arbitration_id: int, handler: Subscriber) -> bool:
        with self._lock:
            handlers = self._subscribers.get(arbitration_id)
            if handlers is None:
                return False
            for index, existing in enumerate(handlers):
                if existing is handler:
                    del handlers[index]
                    if not handlers:
                        del self._subscribers[arbitration_id]
                    return True
            return False

    def dispatch_callbacks(self, wire_frame: CanWireFrame) -> int:
        """Dispatch a locked snapshot and return the number of failures."""

        with self._lock:
            handlers = tuple(self._subscribers.get(wire_frame.frame.arbitration_id, ()))
        callback_errors = 0
        for handler in handlers:
            try:
                handler(wire_frame)
            except Exception as exc:  # noqa: BLE001 - callback failures cannot terminate the runtime worker.
                callback_errors += 1
                logger.error("CAN subscriber failed: %s", exc)
        return callback_errors

    def _worker_main(self) -> None:
        while not self._cancel_event.is_set():
            with self._lock:
                if self._state is not DeviceRuntimeState.ACTIVE:
                    return
            result = self.service_once(receive_timeout_s=self._poll_interval_s)
            if result is None:
                # An adapter may be faulted and deliberately return without
                # touching its file descriptor.  Keep that fail-closed state
                # bounded instead of spinning a CPU while waiting for repair.
                self._cancel_event.wait(self._poll_interval_s)

    def _notify_adapter_error(self, error: Exception) -> None:
        callback = getattr(self._adapter, "on_runtime_error", None)
        if callback is not None:
            callback(error)
        else:
            logger.error("device adapter failed: %s", error)

    def _notify_shutdown_timeout(self) -> None:
        with self._lock:
            if self._shutdown_timeout_reported:
                return
            self._shutdown_timeout_reported = True
        callback = getattr(self._adapter, "on_runtime_shutdown_timeout", None)
        if callback is not None:
            callback()


def decode_can_frame(frame: object) -> CanWireFrame:
    """Validate and decode one complete MCU CAN Wire V1 frame."""

    if not isinstance(frame, CanFrame):
        raise CanFrameValidationError("transport frames must be CanFrame instances")
    if type(frame.arbitration_id) is not int or not 0 <= frame.arbitration_id <= 0x7FF:
        raise CanFrameValidationError("arbitration_id must be a standard 11-bit integer")
    if type(frame.is_extended_id) is not bool or frame.is_extended_id:
        raise CanFrameValidationError("extended CAN frames are not supported")
    if type(frame.is_remote_frame) is not bool or frame.is_remote_frame:
        raise CanFrameValidationError("remote CAN frames are not supported")
    if type(frame.is_error_frame) is not bool or frame.is_error_frame:
        raise CanFrameValidationError("CAN error frames are not protocol frames")
    if not isinstance(frame.data, bytes):
        raise CanFrameValidationError("CAN payload must be immutable bytes")
    if len(frame.data) != MCU_WIRE_DLC:
        raise CanFrameValidationError("CAN Wire V1 requires DLC 8")

    kind = _ID_TO_KIND.get(frame.arbitration_id)
    if kind is None:
        raise CanFrameValidationError("unknown CAN Wire V1 arbitration ID")
    data = frame.data
    if data[0] != MCU_WIRE_VERSION_V1:
        raise CanFrameValidationError("unsupported CAN Wire version")

    if kind in {CanFrameKind.COMMAND, CanFrameKind.STOP}:
        if any(data[index] != 0 for index in (5, 6, 7)):
            raise CanFrameValidationError("command reserved bytes must be zero")
        command_id = int.from_bytes(data[1:3], "big")
        opcode = data[3]
        if kind is CanFrameKind.COMMAND and not (command_id <= 0x7FFF and opcode in _ORDINARY_OPCODES):
            raise CanFrameValidationError("ordinary command ID or opcode is outside its partition")
        if kind is CanFrameKind.STOP and not (command_id >= 0x8000 and opcode == _WireOpcode.STOP):
            raise CanFrameValidationError("STOP command ID or opcode is outside its partition")
        return CanWireFrame(
            frame=frame,
            kind=kind,
            command_id=command_id,
            opcode=opcode,
            retry_count=data[4],
        )

    if kind in {CanFrameKind.ACK, CanFrameKind.STOP_ACK}:
        command_id = int.from_bytes(data[1:3], "big")
        opcode = data[3]
        retry_count = data[4]
        result_code = data[5]
        fault_code = data[6]
        device_mode = data[7]
        if kind is CanFrameKind.ACK:
            valid_partition = command_id <= 0x7FFF and opcode in _ORDINARY_OPCODES
            valid_result = (
                result_code == _WireResult.ACCEPTED
                and fault_code == _WireFault.NONE
                and _WireMode.IDLE <= device_mode <= _WireMode.STOPPED
            ) or (
                result_code == _WireResult.REJECTED
                and fault_code in {_WireFault.DUPLICATE_FRAME, _WireFault.MALFORMED_FRAME}
                and device_mode == _WireMode.FAULTED
            )
        else:
            valid_partition = command_id >= 0x8000 and opcode == _WireOpcode.STOP
            valid_result = (
                result_code == _WireResult.ACCEPTED
                and fault_code == _WireFault.NONE
                and device_mode == _WireMode.STOPPED
            ) or (
                result_code == _WireResult.REJECTED
                and fault_code == _WireFault.STOP_REJECTED
                and device_mode == _WireMode.FAULTED
            )
        if not valid_partition or not valid_result:
            raise CanFrameValidationError("acknowledgement fields violate CAN Wire V1 semantics")
        return CanWireFrame(
            frame=frame,
            kind=kind,
            command_id=command_id,
            opcode=opcode,
            retry_count=retry_count,
            result_code=result_code,
            fault_code=fault_code,
            device_mode=device_mode,
        )

    if data[7] != 0:
        raise CanFrameValidationError("telemetry reserved byte must be zero")
    sequence_no = int.from_bytes(data[1:5], "big")
    fault_code = data[5]
    device_mode = data[6]
    valid_telemetry = (fault_code == _WireFault.NONE and _WireMode.IDLE <= device_mode <= _WireMode.STOPPED) or (
        fault_code in {_WireFault.LINK_LOST, _WireFault.WATCHDOG_EXPIRED} and device_mode == _WireMode.FAULTED
    )
    if not valid_telemetry:
        raise CanFrameValidationError("telemetry fields violate CAN Wire V1 semantics")
    return CanWireFrame(
        frame=frame,
        kind=kind,
        sequence_no=sequence_no,
        fault_code=fault_code,
        device_mode=device_mode,
    )


class SafeCANBus:
    """CAN ``DeviceAdapter`` hosted by one shared :class:`DeviceRuntime`.

    ``CanLinkState`` below is link/protocol health only.  Lifecycle, worker,
    cancellation, bounded planes and callbacks belong to ``self._runtime``.
    The small ``start``/``shutdown`` methods retained on this facade delegate
    to that owner for compatibility with the original Issue #55 API.
    """

    def __init__(
        self,
        transport: CanTransportPort,
        *,
        clock: MonotonicClock | None = None,
        wall_clock: Callable[[], float] | None = None,
        config: CanTransportConfig | None = None,
    ) -> None:
        self._transport = transport
        self._clock = clock or _SystemClock()
        self._wall_clock = wall_clock or time.time
        if not callable(self._wall_clock):
            raise TypeError("wall_clock must be callable")
        self._config = config or CanTransportConfig()
        self._opened = False
        self._state = CanLinkState.NEW
        self._pending_command: _PendingRequest | None = None
        self._pending_stop: _PendingRequest | None = None
        self._dispatching: _Dispatch | None = None
        self._completed: dict[CorrelationKey, frozenset[int]] = {}
        self._completed_order: deque[CorrelationKey] = deque()
        self._timed_out: dict[CorrelationKey, frozenset[int]] = {}
        self._timed_out_order: deque[CorrelationKey] = deque()
        self._next_stop_command_id = self._config.initial_stop_command_id
        self._last_telemetry_sequence: int | None = None
        self._ingress_sequence = 0
        self._last_wall_ts: float | None = None
        self._runtime = DeviceRuntime(
            self,
            command_capacity=self._config.queue_capacity,
            telemetry_capacity=self._config.telemetry_capacity,
            # ``diagnostic_capacity`` is the legacy public name for the
            # health-plane bound.  Honor either setting when callers provide
            # the newer explicit health capacity.
            health_capacity=min(self._config.health_capacity, self._config.diagnostic_capacity),
            max_subscribers_per_id=self._config.max_subscribers_per_id,
            poll_interval_s=self._config.poll_interval_s,
        )

    @property
    def runtime(self) -> DeviceRuntime:
        """The unified runtime owner used by this adapter."""

        return self._runtime

    @property
    def state(self) -> CanLinkState:
        with self._runtime.lock:
            if self._runtime.state in {
                DeviceRuntimeState.DEACTIVATING,
                DeviceRuntimeState.CLEANED,
            }:
                return CanLinkState.SHUTDOWN
            if self._runtime.state in {
                DeviceRuntimeState.CONFIGURING,
                DeviceRuntimeState.CONFIGURED,
                DeviceRuntimeState.ACTIVATING,
            }:
                return CanLinkState.STARTING
            return self._state

    @property
    def running(self) -> bool:
        with self._runtime.lock:
            return self._runtime.state is DeviceRuntimeState.ACTIVE and self._state in {
                CanLinkState.ACTIVE,
                CanLinkState.STOPPING,
            }

    @property
    def queued_count(self) -> int:
        return self._runtime.command_depth

    @property
    def pending_command_id(self) -> int | None:
        with self._runtime.lock:
            if self._pending_stop is not None:
                return self._pending_stop.wire_frame.command_id
            if self._pending_command is not None:
                return self._pending_command.wire_frame.command_id
            if self._dispatching is not None:
                return self._dispatching.wire_frame.command_id
            return None

    def start(self, *, background: bool = True) -> bool:
        return self._runtime.start(background=background)

    def send(self, frame: object) -> CanSendResult:
        try:
            wire_frame = decode_can_frame(frame)
        except CanFrameValidationError as exc:
            self._record_diagnostic(CanDiagnosticCode.INVALID_FRAME, str(exc))
            return CanSendResult(CanSendStatus.INVALID_FRAME, str(exc))
        if wire_frame.kind not in _OUTBOUND_KINDS:
            reason = "host transport only queues command and STOP frames"
            self._record_diagnostic(CanDiagnosticCode.INVALID_FRAME, reason, wire_frame.command_id)
            return CanSendResult(CanSendStatus.INVALID_FRAME, reason, wire_frame.command_id)

        return self._runtime.submit_command(
            wire_frame,
            priority=wire_frame.kind is CanFrameKind.STOP,
            admit=lambda: self._admit_command_locked(wire_frame),
            on_priority=lambda: self._preempt_for_stop_locked("explicit STOP preempted ordinary traffic"),
            on_backpressure=lambda: self._backpressure_locked(wire_frame),
        )

    def _admit_command_locked(self, wire_frame: CanWireFrame) -> CanSendResult:
        runtime_state = self._runtime.state
        if runtime_state in {
            DeviceRuntimeState.NEW,
            DeviceRuntimeState.CONFIGURING,
            DeviceRuntimeState.CONFIGURED,
            DeviceRuntimeState.ACTIVATING,
            DeviceRuntimeState.DEACTIVATING,
            DeviceRuntimeState.CLEANED,
            DeviceRuntimeState.FAILED,
        }:
            return CanSendResult(CanSendStatus.NOT_RUNNING, command_id=wire_frame.command_id)
        if wire_frame.kind is CanFrameKind.COMMAND and self._state is not CanLinkState.ACTIVE:
            return CanSendResult(CanSendStatus.LINK_UNAVAILABLE, command_id=wire_frame.command_id)
        if wire_frame.kind is CanFrameKind.STOP and self._state not in {
            CanLinkState.ACTIVE,
            CanLinkState.STOPPING,
        }:
            return CanSendResult(CanSendStatus.LINK_UNAVAILABLE, command_id=wire_frame.command_id)
        if wire_frame.kind is CanFrameKind.STOP and (
            self._pending_stop is not None
            or (self._dispatching is not None and self._dispatching.wire_frame.kind is CanFrameKind.STOP)
            or any(
                isinstance(queued, CanWireFrame) and queued.kind is CanFrameKind.STOP
                for queued in self._runtime._command_snapshot_locked()
            )
        ):
            reason = "a STOP acknowledgement is already pending"
            self._record_diagnostic_locked(CanDiagnosticCode.CORRELATION_CONFLICT, reason, wire_frame.command_id)
            return CanSendResult(CanSendStatus.CORRELATION_CONFLICT, reason, wire_frame.command_id)
        if self._correlation_id_in_use_locked(wire_frame.kind, wire_frame.command_id):
            reason = "command ID is still retained by the bounded correlation window"
            self._record_diagnostic_locked(CanDiagnosticCode.CORRELATION_CONFLICT, reason, wire_frame.command_id)
            return CanSendResult(CanSendStatus.CORRELATION_CONFLICT, reason, wire_frame.command_id)
        return CanSendResult(CanSendStatus.QUEUED, command_id=wire_frame.command_id)

    def _backpressure_locked(self, wire_frame: CanWireFrame) -> CanSendResult:
        reason = "outbound command plane capacity reached"
        self._record_diagnostic_locked(CanDiagnosticCode.BACKPRESSURE, reason, wire_frame.command_id)
        return CanSendResult(CanSendStatus.BACKPRESSURE, reason, wire_frame.command_id)

    def configure(self) -> bool:
        """Prepare protocol state; the runtime owns the transition itself."""

        with self._runtime.lock:
            return self._state is CanLinkState.NEW

    def activate(self) -> bool:
        """Open the injected port without creating a worker."""

        with self._runtime.lock:
            self._state = CanLinkState.STARTING
        try:
            self._transport.open()
        except CanTransportError as exc:
            with self._runtime.lock:
                self._state = CanLinkState.LINK_LOST
                self._record_diagnostic_locked(CanDiagnosticCode.LINK_LOST, str(exc))
            return False
        with self._runtime.lock:
            self._opened = True
            self._state = (
                CanLinkState.ACTIVE if self._runtime.state is DeviceRuntimeState.ACTIVATING else CanLinkState.SHUTDOWN
            )
        return True

    def service_once(self, *, receive_timeout_s: float = 0.0) -> CanReceiveResult | None:
        """Compatibility facade delegating polling to the unified runtime."""

        result = self._runtime.service_once(receive_timeout_s=receive_timeout_s)
        return result if isinstance(result, CanReceiveResult) else None

    def poll(self, receive_timeout_s: float) -> CanReceiveResult | None:
        """Poll one transport cycle; called only by ``DeviceRuntime``."""

        with self._runtime.lock:
            if self._state not in {CanLinkState.ACTIVE, CanLinkState.STOPPING}:
                return None
            dispatch = self._next_dispatch_locked(self._clock.monotonic())
            if dispatch is not None:
                self._dispatching = dispatch

        if dispatch is not None:
            try:
                self._transport.send(dispatch.wire_frame.frame)
            except CanTransportError as exc:
                self._handle_transport_error(exc)
                return None
            with self._runtime.lock:
                if self._dispatching is not dispatch or self._runtime.state is not DeviceRuntimeState.ACTIVE:
                    return None
                self._dispatching = None
                self._record_dispatch_locked(dispatch, self._clock.monotonic())

        try:
            received = self._transport.receive(float(receive_timeout_s))
        except CanTransportError as exc:
            self._handle_transport_error(exc)
            return None
        if received is None:
            return None
        return self._handle_received(received)

    def recover(self) -> bool:
        with self._runtime.lock:
            if self._state not in {CanLinkState.BUS_OFF, CanLinkState.LINK_LOST}:
                return False
            token = self._runtime.begin_operation()
            if token is None:
                return False
        try:
            recovered = self._transport.recover()
        except CanTransportError as exc:
            self._handle_transport_error(exc)
            self._runtime.end_operation(token)
            return False
        if not recovered:
            self._runtime.end_operation(token)
            return False
        with self._runtime.lock:
            applied = self._runtime.operation_is_current(token) and self._state in {
                CanLinkState.BUS_OFF,
                CanLinkState.LINK_LOST,
            }
            if applied:
                self._runtime._clear_commands_locked()
                self._pending_command = None
                self._pending_stop = None
                self._dispatching = None
                self._last_telemetry_sequence = None
                self._state = CanLinkState.ACTIVE
        self._runtime.end_operation(token)
        return applied

    def shutdown(self, *, timeout_s: float | None = None) -> bool:
        timeout = self._config.shutdown_timeout_s if timeout_s is None else timeout_s
        if timeout is None:
            timeout = self._config.shutdown_timeout_s
        return self._runtime.shutdown(timeout_s=timeout)

    def deactivate(self) -> bool:
        """Close the port after the runtime has cancelled and joined its worker."""

        with self._runtime.lock:
            if self._runtime._shutdown_requested or self._state not in {
                CanLinkState.BUS_OFF,
                CanLinkState.LINK_LOST,
            }:
                self._state = CanLinkState.SHUTDOWN
            self._runtime._clear_commands_locked()
            self._pending_command = None
            self._pending_stop = None
            self._dispatching = None
            opened = self._opened
        if not opened:
            return True
        try:
            self._transport.close()
        except CanTransportError as exc:
            with self._runtime.lock:
                self._record_diagnostic_locked(CanDiagnosticCode.LINK_LOST, str(exc))
            return False
        with self._runtime.lock:
            self._opened = False
        return True

    def cleanup(self) -> bool:
        """Destroy adapter data planes without reopening or replaying traffic."""

        with self._runtime.lock:
            self._runtime._clear_commands_locked()
            self._pending_command = None
            self._pending_stop = None
            self._dispatching = None
            self._last_telemetry_sequence = None
            self._ingress_sequence = 0
            self._last_wall_ts = None
            self._runtime._telemetry_queue.clear()
            self._runtime._subscribers.clear()
            return not self._opened

    def subscribe(self, arbitration_id: int, handler: Subscriber) -> bool:
        if type(arbitration_id) is not int or arbitration_id not in _ID_TO_KIND:
            raise ValueError("subscription requires a known CAN Wire V1 arbitration ID")
        if not callable(handler):
            raise TypeError("handler must be callable")
        return self._runtime.subscribe(arbitration_id, handler)

    def unsubscribe(self, arbitration_id: int, handler: Subscriber) -> bool:
        return self._runtime.unsubscribe(arbitration_id, handler)

    def get_error_count(self) -> int:
        return self._runtime.error_count

    def diagnostics(self) -> tuple[CanDiagnostic, ...]:
        return tuple(item for item in self._runtime.health_records() if isinstance(item, CanDiagnostic))

    def on_runtime_error(self, error: Exception) -> None:
        with self._runtime.lock:
            self._handle_transport_error(CanLinkLostError(str(error)))

    def on_runtime_shutdown_requested(self) -> None:
        """Cancel protocol work without closing a port used by a live poll."""

        with self._runtime.lock:
            self._runtime._clear_commands_locked()
            self._pending_command = None
            self._pending_stop = None
            self._dispatching = None
            self._state = CanLinkState.SHUTDOWN

    def on_runtime_shutdown_timeout(self) -> None:
        self._record_diagnostic(
            CanDiagnosticCode.SHUTDOWN_TIMEOUT,
            "device runtime worker did not stop before the shutdown deadline",
        )

    def _next_dispatch_locked(self, now: float) -> _Dispatch | None:
        if self._pending_stop is not None:
            return self._retry_or_timeout_locked(
                self._pending_stop,
                now,
                self._config.stop_retry_budget,
                CanDiagnosticCode.STOP_TIMEOUT,
            )
        if self._pending_command is not None:
            dispatch = self._retry_or_timeout_locked(
                self._pending_command,
                now,
                self._config.ack_retry_budget,
                CanDiagnosticCode.ACK_TIMEOUT,
            )
            if dispatch is not None or self._pending_command is not None:
                return dispatch
            stop_frame = self._new_stop_frame_locked()
            self._state = CanLinkState.STOPPING
            return _Dispatch(stop_frame, False)
        queued = self._runtime._pop_command_locked()
        if queued is None:
            return None
        if not isinstance(queued, CanWireFrame):
            raise RuntimeError("runtime command plane contained a non-CAN item")
        return _Dispatch(queued, False)

    def _retry_or_timeout_locked(
        self,
        pending: _PendingRequest,
        now: float,
        retry_budget: int,
        timeout_code: CanDiagnosticCode,
    ) -> _Dispatch | None:
        if now < pending.deadline:
            return None
        current_retry = pending.wire_frame.retry_count
        if current_retry is None:
            raise RuntimeError("pending command is missing retry_count")
        if pending.retry_budget_used < retry_budget and current_retry < 0xFF:
            return _Dispatch(_with_retry_count(pending.wire_frame, current_retry + 1), True)

        command_id = pending.wire_frame.command_id
        self._record_diagnostic_locked(
            timeout_code,
            f"{pending.wire_frame.kind} acknowledgement deadline expired",
            command_id,
        )
        self._remember_correlation_locked(self._timed_out, self._timed_out_order, pending)
        if pending.wire_frame.kind is CanFrameKind.STOP:
            self._pending_stop = None
            self._runtime._clear_commands_locked()
            self._state = CanLinkState.LINK_LOST
        else:
            self._pending_command = None
            self._runtime._clear_commands_locked()
        return None

    def _record_dispatch_locked(self, dispatch: _Dispatch, now: float) -> None:
        wire_frame = dispatch.wire_frame
        retry_count = wire_frame.retry_count
        if retry_count is None:
            raise RuntimeError("outbound command is missing retry_count")
        if wire_frame.kind is CanFrameKind.COMMAND:
            if dispatch.is_retry:
                pending = self._pending_command
                if pending is None:
                    raise RuntimeError("ordinary retry has no pending command")
                pending.wire_frame = wire_frame
                pending.deadline = now + self._config.ack_timeout_s
                pending.retry_budget_used += 1
                pending.sent_retry_counts.add(retry_count)
            else:
                self._pending_command = _PendingRequest(
                    wire_frame,
                    now + self._config.ack_timeout_s,
                    0,
                    {retry_count},
                )
        elif wire_frame.kind is CanFrameKind.STOP:
            self._state = CanLinkState.STOPPING
            if dispatch.is_retry:
                pending = self._pending_stop
                if pending is None:
                    raise RuntimeError("STOP retry has no pending STOP")
                pending.wire_frame = wire_frame
                pending.deadline = now + self._config.stop_timeout_s
                pending.retry_budget_used += 1
                pending.sent_retry_counts.add(retry_count)
            else:
                self._pending_stop = _PendingRequest(
                    wire_frame,
                    now + self._config.stop_timeout_s,
                    0,
                    {retry_count},
                )

    def _handle_received(self, frame: object) -> CanReceiveResult:
        try:
            wire_frame = decode_can_frame(frame)
        except CanFrameValidationError as exc:
            self._record_diagnostic(CanDiagnosticCode.INVALID_FRAME, str(exc))
            return CanReceiveResult(CanReceiveStatus.INVALID_FRAME, reason=str(exc))
        if wire_frame.kind not in _INBOUND_KINDS:
            reason = "transport receive path only accepts ack, stop_ack, and telemetry frames"
            self._record_diagnostic(CanDiagnosticCode.INVALID_FRAME, reason, wire_frame.command_id)
            return CanReceiveResult(CanReceiveStatus.INVALID_FRAME, wire_frame=wire_frame, reason=reason)

        with self._runtime.lock:
            envelope = self._make_envelope_locked(wire_frame)
            if envelope is None:
                return CanReceiveResult(
                    CanReceiveStatus.INVALID_FRAME,
                    wire_frame=wire_frame,
                    reason="wall-clock observation regressed or is not finite",
                )
            status, confirmed = self._correlate_received_locked(wire_frame)
            envelope = replace(envelope, health=self._state)
            if status is not CanReceiveStatus.ACCEPTED:
                return CanReceiveResult(status, wire_frame=wire_frame, envelope=envelope, confirmed=False)
            if wire_frame.kind is CanFrameKind.TELEMETRY:
                self._runtime.publish_telemetry(wire_frame)
                dispatch_frame = self._runtime.take_telemetry()
            else:
                dispatch_frame = wire_frame

        if not isinstance(dispatch_frame, CanWireFrame):
            raise RuntimeError("telemetry plane lost an accepted CAN frame")
        callback_errors = self._runtime.dispatch_callbacks(dispatch_frame)
        if callback_errors:
            with self._runtime.lock:
                for _ in range(callback_errors):
                    self._record_diagnostic_locked(
                        CanDiagnosticCode.SUBSCRIBER_ERROR,
                        "subscriber callback raised an exception",
                        wire_frame.command_id,
                    )
        return CanReceiveResult(
            CanReceiveStatus.ACCEPTED,
            wire_frame=wire_frame,
            envelope=envelope,
            confirmed=confirmed,
            callback_errors=callback_errors,
        )

    def _make_envelope_locked(self, wire_frame: CanWireFrame) -> CanTransportEnvelope | None:
        sequence = self._ingress_sequence
        self._ingress_sequence += 1
        try:
            wall_ts = self._wall_clock()
        except Exception as exc:  # noqa: BLE001 - clock faults fail closed at ingress.
            self._fail_clock_locked(f"wall clock failed: {exc}")
            return None
        if isinstance(wall_ts, bool) or not isinstance(wall_ts, int | float) or not math.isfinite(wall_ts):
            self._fail_clock_locked("wall-clock observation is not finite")
            return None
        wall_ts = float(wall_ts)
        if self._last_wall_ts is not None and wall_ts < self._last_wall_ts:
            self._fail_clock_locked("wall-clock observation moved backwards")
            return None
        self._last_wall_ts = wall_ts
        return CanTransportEnvelope(
            source=self._config.source,
            interface=self._config.interface,
            sequence=sequence,
            monotonic_ts=self._clock.monotonic(),
            wall_ts=wall_ts,
            health=self._state,
            wire_frame=wire_frame,
        )

    def _fail_clock_locked(self, detail: str) -> None:
        self._handle_transport_error(CanLinkLostError(detail))
        self._record_diagnostic_locked(CanDiagnosticCode.CLOCK_ROLLBACK, detail)

    def _correlate_received_locked(self, wire_frame: CanWireFrame) -> tuple[CanReceiveStatus, bool]:
        if wire_frame.kind is CanFrameKind.TELEMETRY:
            sequence_no = wire_frame.sequence_no
            if sequence_no is None:
                raise RuntimeError("telemetry is missing sequence_no")
            if self._last_telemetry_sequence is not None:
                delta = (sequence_no - self._last_telemetry_sequence) & 0xFFFFFFFF
                if delta == 0:
                    self._record_diagnostic_locked(
                        CanDiagnosticCode.DUPLICATE_TELEMETRY,
                        "duplicate telemetry ignored",
                    )
                    return CanReceiveStatus.DUPLICATE, False
                if delta >= 0x80000000:
                    self._record_diagnostic_locked(
                        CanDiagnosticCode.STALE_TELEMETRY,
                        "stale or ambiguous telemetry ignored",
                    )
                    return CanReceiveStatus.LATE, False
            self._last_telemetry_sequence = sequence_no
            if wire_frame.fault_code != _WireFault.NONE:
                self._handle_transport_error(
                    CanLinkLostError(f"MCU fault telemetry reported fault code {wire_frame.fault_code}")
                )
            return CanReceiveStatus.ACCEPTED, False
        key = _correlation_key(wire_frame)
        retry_count = wire_frame.retry_count
        if retry_count is None:
            raise RuntimeError("acknowledgement is missing retry_count")
        pending = self._pending_stop if wire_frame.kind is CanFrameKind.STOP_ACK else self._pending_command
        if (
            pending is not None
            and key == _response_key(pending.wire_frame)
            and retry_count in pending.sent_retry_counts
        ):
            self._remember_correlation_locked(self._completed, self._completed_order, pending)
            if wire_frame.kind is CanFrameKind.STOP_ACK:
                self._pending_stop = None
                self._runtime._clear_commands_locked()
                if wire_frame.result_code == _WireResult.ACCEPTED:
                    self._state = CanLinkState.SAFE_STOPPED
                else:
                    self._state = CanLinkState.LINK_LOST
                    self._record_diagnostic_locked(
                        CanDiagnosticCode.STOP_REJECTED,
                        "MCU returned a rejected STOP acknowledgement",
                        wire_frame.command_id,
                    )
            else:
                self._pending_command = None
                if wire_frame.result_code != _WireResult.ACCEPTED:
                    self._runtime._clear_commands_locked()
                    self._state = CanLinkState.LINK_LOST
                    self._record_diagnostic_locked(
                        CanDiagnosticCode.COMMAND_REJECTED,
                        "MCU returned a rejected ordinary acknowledgement",
                        wire_frame.command_id,
                    )
                    return CanReceiveStatus.ACCEPTED, False
            return CanReceiveStatus.ACCEPTED, wire_frame.result_code == _WireResult.ACCEPTED

        if retry_count in self._completed.get(key, ()):
            self._record_diagnostic_locked(
                CanDiagnosticCode.DUPLICATE_ACK,
                "duplicate acknowledgement ignored",
                wire_frame.command_id,
            )
            return CanReceiveStatus.DUPLICATE, False
        if retry_count in self._timed_out.get(key, ()):
            self._record_diagnostic_locked(
                CanDiagnosticCode.LATE_ACK,
                "late acknowledgement did not change transport state",
                wire_frame.command_id,
            )
            return CanReceiveStatus.LATE, False
        self._record_diagnostic_locked(
            CanDiagnosticCode.UNCORRELATED_ACK,
            "acknowledgement did not match a dispatched attempt",
            wire_frame.command_id,
        )
        return CanReceiveStatus.UNCORRELATED, False

    def _handle_transport_error(self, error: CanTransportError) -> None:
        with self._runtime.lock:
            if self._pending_command is not None:
                self._remember_correlation_locked(
                    self._timed_out,
                    self._timed_out_order,
                    self._pending_command,
                )
            if self._pending_stop is not None:
                self._remember_correlation_locked(
                    self._timed_out,
                    self._timed_out_order,
                    self._pending_stop,
                )
            self._pending_command = None
            self._pending_stop = None
            self._dispatching = None
            self._runtime._clear_commands_locked()
            if isinstance(error, CanBusOffError):
                code = CanDiagnosticCode.BUS_OFF
                next_state = CanLinkState.BUS_OFF
            else:
                code = CanDiagnosticCode.LINK_LOST
                next_state = CanLinkState.LINK_LOST
            if self._state is not CanLinkState.SHUTDOWN:
                self._state = next_state
            self._record_diagnostic_locked(code, str(error))

    def _preempt_for_stop_locked(self, detail: str) -> None:
        preempted = self._runtime.command_depth
        self._runtime._clear_commands_locked()
        self._state = CanLinkState.STOPPING
        if self._pending_command is not None:
            sent_retry_counts = set(self._pending_command.sent_retry_counts)
            if self._dispatching is not None and self._dispatching.wire_frame.kind is CanFrameKind.COMMAND:
                retry_count = self._dispatching.wire_frame.retry_count
                if retry_count is not None:
                    sent_retry_counts.add(retry_count)
            self._remember_correlation_locked(
                self._timed_out,
                self._timed_out_order,
                _PendingRequest(
                    self._pending_command.wire_frame,
                    self._pending_command.deadline,
                    self._pending_command.retry_budget_used,
                    sent_retry_counts,
                ),
            )
            self._pending_command = None
            preempted += 1
        elif self._dispatching is not None and self._dispatching.wire_frame.kind is CanFrameKind.COMMAND:
            retry_count = self._dispatching.wire_frame.retry_count
            if retry_count is None:
                raise RuntimeError("dispatching command is missing retry_count")
            self._remember_correlation_locked(
                self._timed_out,
                self._timed_out_order,
                _PendingRequest(self._dispatching.wire_frame, 0.0, 0, {retry_count}),
            )
            preempted += 1
        if self._dispatching is not None and self._dispatching.wire_frame.kind is CanFrameKind.COMMAND:
            self._dispatching = None
        if preempted:
            self._record_diagnostic_locked(CanDiagnosticCode.STOP_PREEMPTED, detail)

    def _new_stop_frame_locked(self) -> CanWireFrame:
        for _ in range(self._config.correlation_capacity + 1):
            command_id = self._next_stop_command_id
            self._next_stop_command_id = 0x8000 if command_id == 0xFFFF else command_id + 1
            if not self._correlation_id_in_use_locked(CanFrameKind.STOP, command_id):
                data = bytes(
                    [
                        MCU_WIRE_VERSION_V1,
                        command_id >> 8,
                        command_id & 0xFF,
                        _WireOpcode.STOP,
                        0,
                        0,
                        0,
                        0,
                    ]
                )
                return decode_can_frame(CanFrame(MCU_CAN_ID_STOP, data))
        raise RuntimeError("bounded STOP correlation window exhausted")

    def _correlation_id_in_use_locked(self, kind: CanFrameKind, command_id: int | None) -> bool:
        if command_id is None:
            return False
        request_kind = CanFrameKind.STOP if kind in {CanFrameKind.STOP, CanFrameKind.STOP_ACK} else CanFrameKind.COMMAND
        candidates = [item for item in self._runtime._command_snapshot_locked() if isinstance(item, CanWireFrame)]
        if self._dispatching is not None:
            candidates.append(self._dispatching.wire_frame)
        if self._pending_command is not None:
            candidates.append(self._pending_command.wire_frame)
        if self._pending_stop is not None:
            candidates.append(self._pending_stop.wire_frame)
        if any(candidate.kind is request_kind and candidate.command_id == command_id for candidate in candidates):
            return True
        response_kind = CanFrameKind.STOP_ACK if request_kind is CanFrameKind.STOP else CanFrameKind.ACK
        return any(key[0] is response_kind and key[1] == command_id for key in (*self._completed, *self._timed_out))

    def _remember_correlation_locked(
        self,
        target: dict[CorrelationKey, frozenset[int]],
        order: deque[CorrelationKey],
        pending: _PendingRequest,
    ) -> None:
        key = _response_key(pending.wire_frame)
        if key in target:
            try:
                order.remove(key)
            except ValueError:
                pass
        target[key] = frozenset(pending.sent_retry_counts)
        order.append(key)
        while len(order) > self._config.correlation_capacity:
            target.pop(order.popleft(), None)

    def _record_diagnostic_locked(
        self,
        code: CanDiagnosticCode,
        detail: str,
        command_id: int | None = None,
    ) -> None:
        self._runtime._record_health_locked(CanDiagnostic(code, self._clock.monotonic(), detail, command_id))

    def _record_diagnostic(
        self,
        code: CanDiagnosticCode,
        detail: str,
        command_id: int | None = None,
    ) -> None:
        with self._runtime.lock:
            self._record_diagnostic_locked(code, detail, command_id)


def _with_retry_count(wire_frame: CanWireFrame, retry_count: int) -> CanWireFrame:
    data = bytearray(wire_frame.frame.data)
    data[4] = retry_count
    return decode_can_frame(
        CanFrame(
            wire_frame.frame.arbitration_id,
            bytes(data),
            wire_frame.frame.is_extended_id,
            wire_frame.frame.is_remote_frame,
            wire_frame.frame.is_error_frame,
        )
    )


def _correlation_key(wire_frame: CanWireFrame) -> CorrelationKey:
    if wire_frame.command_id is None or wire_frame.opcode is None:
        raise RuntimeError("correlated frame is missing command fields")
    return wire_frame.kind, wire_frame.command_id, wire_frame.opcode


def _response_key(wire_frame: CanWireFrame) -> CorrelationKey:
    if wire_frame.command_id is None or wire_frame.opcode is None:
        raise RuntimeError("correlated frame is missing command fields")
    response_kind = CanFrameKind.ACK if wire_frame.kind is CanFrameKind.COMMAND else CanFrameKind.STOP_ACK
    return response_kind, wire_frame.command_id, wire_frame.opcode
