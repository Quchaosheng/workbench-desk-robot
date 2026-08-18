from enum import StrEnum


class McuState(StrEnum):
    IDLE = "idle"
    EXECUTING = "executing"
    SAFE_STOP = "safe_stop"
    FAULT = "fault"


class VirtualMcu:
    """Tiny deterministic model of the P0 safety boundary."""

    def __init__(self) -> None:
        self.state = McuState.IDLE
        self.fault_code: str | None = None

    def command(self, command: str) -> McuState:
        if command == "stop":
            self.state = McuState.SAFE_STOP
        elif command == "reset" and self.state in {McuState.SAFE_STOP, McuState.FAULT}:
            self.state = McuState.IDLE
            self.fault_code = None
        elif command == "execute" and self.state == McuState.IDLE:
            self.state = McuState.EXECUTING
        elif command == "complete" and self.state == McuState.EXECUTING:
            self.state = McuState.IDLE
        return self.state

    def watchdog_timeout(self) -> McuState:
        self.state = McuState.FAULT
        self.fault_code = "WATCHDOG_TIMEOUT"
        return self.state
