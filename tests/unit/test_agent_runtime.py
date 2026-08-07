import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "libs/contracts"), str(ROOT / "services/agent_runtime"), str(ROOT / "tools/scripts")]

from local_runner import plan_offline
from workbench_agent_runtime import build_kitting_plan, build_template_plan, classify_template_task


class PlannerTests(unittest.TestCase):
    def test_template_plan_contains_only_semantic_actions(self) -> None:
        plan = build_template_plan("Place the red block in the tray")
        self.assertEqual([step.action.action_type.value for step in plan.steps], ["observe", "grasp", "place"])
        self.assertNotIn("joint", plan.model_dump_json())

    def test_offline_template_plan_needs_no_model_provider(self) -> None:
        plan = build_template_plan("把红色模块放进托盘")
        self.assertEqual(plan.model_route, "template")
        self.assertEqual(plan.planner, "template-v1")

    def test_diverse_tasks_produce_bounded_semantic_graphs(self) -> None:
        cases = {
            "Assemble a three-part kit in the tray": ("task-kit-three-parts", 9),
            "Inspect all three workpieces": ("task-inspect-workpieces", 3),
            "Clear the blocked path and place the red block": ("task-clear-workspace", 6),
        }
        for goal, (task_id, step_count) in cases.items():
            with self.subTest(goal=goal):
                plan = build_template_plan(goal)
                self.assertEqual(plan.task_id, task_id)
                self.assertEqual(len(plan.steps), step_count)
                self.assertNotIn("joint", plan.model_dump_json())
                self.assertNotIn("velocity", plan.model_dump_json())

    def test_task_classifier_fails_closed_for_unsupported_goals(self) -> None:
        self.assertEqual(classify_template_task("请完成三件套齐套"), "task-kit-three-parts")
        with self.assertRaises(ValueError):
            classify_template_task("Do something clever")

    def test_task_classifier_does_not_match_keywords_inside_other_words(self) -> None:
        self.assertEqual(classify_template_task("Clearly inspect all three workpieces"), "task-inspect-workpieces")
        for unsupported in ("Move the toolkit to a shelf", "Report checkpoint status", "Find the infrared sensor"):
            with self.subTest(goal=unsupported), self.assertRaises(ValueError):
                classify_template_task(unsupported)

    def test_plan_builders_reject_ambiguous_or_malformed_entity_ids(self) -> None:
        for invalid_ids in ("red_block", [], ["red_block", "red_block"], ["red_block", ""]):
            with self.subTest(part_ids=invalid_ids), self.assertRaises(ValueError):
                build_kitting_plan("Assemble the kit", invalid_ids)

    def test_offline_runner_reports_the_selected_planner_version(self) -> None:
        payload = plan_offline("Assemble a three-part kit in the tray")
        self.assertEqual(payload["provider"], "template-v2")
        self.assertEqual(payload["task_graph"]["task_id"], "task-kit-three-parts")


if __name__ == "__main__":
    unittest.main()
