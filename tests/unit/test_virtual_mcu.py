import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "firmware/virtual_mcu"))

from workbench_virtual_mcu import (
    McuCommandRejection,
    McuCommandStatus,
    McuState,
    VirtualMcu,
)


class VirtualMcuTests(unittest.TestCase):
    def test_stop_and_watchdog_enter_safe_states(self) -> None:
        mcu = VirtualMcu()
        self.assertEqual(mcu.command("execute").state, McuState.EXECUTING)
        self.assertEqual(mcu.command("complete").state, McuState.IDLE)
        self.assertEqual(mcu.command("execute").state, McuState.EXECUTING)
        self.assertEqual(mcu.command("stop").state, McuState.SAFE_STOP)
        self.assertEqual(mcu.command("reset").state, McuState.IDLE)
        self.assertEqual(mcu.watchdog_timeout(), McuState.FAULT)

    def test_unknown_empty_non_string_and_malformed_commands_are_rejected(self) -> None:
        for command, reason in (
            ("typo", McuCommandRejection.UNKNOWN),
            ("", McuCommandRejection.EMPTY),
            (None, McuCommandRejection.NON_STRING),
            (" execute", McuCommandRejection.MALFORMED),
        ):
            with self.subTest(command=command):
                mcu = VirtualMcu()
                result = mcu.command(command)

                self.assertEqual(result.status, McuCommandStatus.REJECTED)
                self.assertTrue(result.rejected)
                self.assertFalse(result.accepted)
                self.assertEqual(result.reason, reason)
                self.assertEqual(result.state, McuState.IDLE)
                self.assertIsNone(mcu.fault_code)

    def test_rejected_state_transitions_do_not_mutate_state_or_fault(self) -> None:
        cases = (
            (McuState.IDLE, None, "complete"),
            (McuState.EXECUTING, None, "execute"),
            (McuState.EXECUTING, None, "reset"),
            (McuState.SAFE_STOP, None, "execute"),
            (McuState.FAULT, "WATCHDOG_TIMEOUT", "execute"),
        )
        for state, fault_code, command in cases:
            with self.subTest(state=state, command=command):
                mcu = VirtualMcu()
                mcu.state = state
                mcu.fault_code = fault_code

                result = mcu.command(command)

                self.assertEqual(result.status, McuCommandStatus.REJECTED)
                self.assertEqual(result.reason, McuCommandRejection.INVALID_STATE)
                self.assertEqual(result.state, state)
                self.assertEqual(mcu.state, state)
                self.assertEqual(mcu.fault_code, fault_code)

    def test_reset_from_fault_is_the_only_fault_clear_path(self) -> None:
        mcu = VirtualMcu()
        mcu.watchdog_timeout()

        result = mcu.command("reset")

        self.assertEqual(result.status, McuCommandStatus.ACCEPTED)
        self.assertEqual(result.state, McuState.IDLE)
        self.assertIsNone(mcu.fault_code)

    def test_stop_is_accepted_from_every_state_and_is_idempotent(self) -> None:
        for state in McuState:
            with self.subTest(state=state):
                mcu = VirtualMcu()
                mcu.state = state
                mcu.fault_code = "WATCHDOG_TIMEOUT" if state is McuState.FAULT else None

                first = mcu.command("stop")
                second = mcu.command("stop")

                self.assertEqual(first.status, McuCommandStatus.ACCEPTED)
                self.assertEqual(second.status, McuCommandStatus.ACCEPTED)
                self.assertEqual(first.state, McuState.SAFE_STOP)
                self.assertEqual(second.state, McuState.SAFE_STOP)
                self.assertEqual(mcu.fault_code, "WATCHDOG_TIMEOUT" if state is McuState.FAULT else None)

    def test_command_matrix_has_one_explicit_outcome_per_state(self) -> None:
        expected = {
            McuState.IDLE: {
                "stop": True,
                "reset": False,
                "execute": True,
                "complete": False,
            },
            McuState.EXECUTING: {
                "stop": True,
                "reset": False,
                "execute": False,
                "complete": True,
            },
            McuState.SAFE_STOP: {
                "stop": True,
                "reset": True,
                "execute": False,
                "complete": False,
            },
            McuState.FAULT: {
                "stop": True,
                "reset": True,
                "execute": False,
                "complete": False,
            },
        }
        for state, commands in expected.items():
            for command, accepted in commands.items():
                with self.subTest(state=state, command=command):
                    mcu = VirtualMcu()
                    mcu.state = state
                    mcu.fault_code = "WATCHDOG_TIMEOUT" if state is McuState.FAULT else None
                    result = mcu.command(command)

                    self.assertEqual(result.accepted, accepted)


if __name__ == "__main__":
    unittest.main()
