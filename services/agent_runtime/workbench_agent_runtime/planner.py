from workbench_contracts import ActionType, SemanticAction, TaskGraph, TaskStep


def build_template_plan(goal: str, block_id: str = "red_block", tray_id: str = "tray") -> TaskGraph:
    """Return the deterministic P0 plan. A model may propose a graph later, never actions below this layer."""
    normalized = goal.lower()
    if "red" not in normalized and "红" not in goal:
        raise ValueError("P0 template accepts only the known red-block task")

    steps = [
        TaskStep(
            step_id="observe-block",
            action=SemanticAction(action_id="act-001", action_type=ActionType.OBSERVE, target_id=block_id),
        ),
        TaskStep(
            step_id="grasp-block",
            action=SemanticAction(action_id="act-002", action_type=ActionType.GRASP, target_id=block_id),
            depends_on=["observe-block"],
        ),
        TaskStep(
            step_id="place-block",
            action=SemanticAction(
                action_id="act-003",
                action_type=ActionType.PLACE,
                target_id=block_id,
                parameters={"destination_id": tray_id},
            ),
            depends_on=["grasp-block"],
        ),
    ]
    return TaskGraph(task_id="task-place-red-block", goal=goal, steps=steps, planner="template-v1")
