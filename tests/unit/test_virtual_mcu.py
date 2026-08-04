import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "firmware/virtual_mcu"))

from workbench_virtual_mcu import McuState, VirtualMcu


class VirtualMcuTests(unittest.TestCase):
    def test_stop_and_watchdog_enter_safe_states(self) -> None:
        mcu = VirtualMcu()
        self.assertEqual(mcu.command("execute"), McuState.EXECUTING)
        self.assertEqual(mcu.command("complete"), McuState.IDLE)
        self.assertEqual(mcu.command("execute"), McuState.EXECUTING)
        self.assertEqual(mcu.command("stop"), McuState.SAFE_STOP)
        self.assertEqual(mcu.command("reset"), McuState.IDLE)
        self.assertEqual(mcu.watchdog_timeout(), McuState.FAULT)


if __name__ == "__main__":
    unittest.main()
