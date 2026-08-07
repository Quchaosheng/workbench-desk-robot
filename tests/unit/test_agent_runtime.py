import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "libs/contracts"), str(ROOT / "services/agent_runtime")]

from workbench_agent_runtime import build_template_plan


class PlannerTests(unittest.TestCase):
    def test_template_plan_contains_only_semantic_actions(self) -> None:
        plan = build_template_plan("Place the red block in the tray")
        self.assertEqual([step.action.action_type.value for step in plan.steps], ["observe", "grasp", "place"])
        self.assertNotIn("joint", plan.model_dump_json())

    def test_offline_template_plan_needs_no_model_provider(self) -> None:
        plan = build_template_plan("把红色模块放进托盘")
        self.assertEqual(plan.model_route, "template")
        self.assertEqual(plan.planner, "template-v1")


if __name__ == "__main__":
    unittest.main()
