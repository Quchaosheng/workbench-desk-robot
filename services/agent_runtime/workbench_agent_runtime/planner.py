import re
from collections.abc import Sequence

from workbench_contracts import ActionType, SemanticAction, TaskGraph, TaskStep

DEFAULT_KIT_PARTS = ("red_block", "blue_cylinder", "green_gear")
DEFAULT_INSPECTION_ENTITIES = ("red_block", "blue_cylinder", "green_gear")


def _matches_task_keyword(text: str, english: tuple[str, ...], chinese: tuple[str, ...]) -> bool:
    english_match = any(re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) for keyword in english)
    return english_match or any(keyword in text for keyword in chinese)


def _validate_identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _validate_entity_ids(values: Sequence[str], label: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise ValueError(f"{label} must be a sequence of entity IDs, not a string")
    normalized = tuple(values)
    if not normalized or any(not isinstance(value, str) or not value.strip() for value in normalized):
        raise ValueError(f"{label} requires non-empty entity IDs")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} requires unique entity IDs")
    return normalized


def classify_template_task(goal: str) -> str:
    if not isinstance(goal, str):
        raise ValueError("task goal must be a string")
    normalized = goal.strip().lower()
    if not normalized:
        raise ValueError("task goal must not be empty")
    if _matches_task_keyword(
        normalized,
        ("clear", "clearance", "blocked", "obstacle"),
        ("清障", "障碍", "挡路", "移开"),
    ):
        return "task-clear-workspace"
    if _matches_task_keyword(normalized, ("kit", "kitting", "three-part"), ("套件", "齐套", "配套", "三件")):
        return "task-kit-three-parts"
    if _matches_task_keyword(
        normalized,
        ("inspect", "inspection", "check"),
        ("检查", "检验", "核验", "质检"),
    ):
        return "task-inspect-workpieces"
    if _matches_task_keyword(normalized, ("red",), ("红",)):
        return "task-place-red-block"
    raise ValueError("template planner supports place, kitting, inspection, and clear-workspace tasks")


def build_place_plan(goal: str, block_id: str = "red_block", tray_id: str = "tray") -> TaskGraph:
    block_id = _validate_identifier(block_id, "block_id")
    tray_id = _validate_identifier(tray_id, "tray_id")
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


def build_kitting_plan(
    goal: str,
    part_ids: Sequence[str] = DEFAULT_KIT_PARTS,
    tray_id: str = "kit_tray",
) -> TaskGraph:
    part_ids = _validate_entity_ids(part_ids, "kitting")
    tray_id = _validate_identifier(tray_id, "tray_id")
    steps: list[TaskStep] = []
    action_index = 1
    for part_id in part_ids:
        suffix = part_id.replace("_", "-")
        observe_step = f"observe-{suffix}"
        grasp_step = f"grasp-{suffix}"
        steps.extend(
            [
                TaskStep(
                    step_id=observe_step,
                    action=SemanticAction(
                        action_id=f"act-{action_index:03d}",
                        action_type=ActionType.OBSERVE,
                        target_id=part_id,
                        parameters={"required_confidence": 0.8},
                    ),
                ),
                TaskStep(
                    step_id=grasp_step,
                    action=SemanticAction(
                        action_id=f"act-{action_index + 1:03d}",
                        action_type=ActionType.GRASP,
                        target_id=part_id,
                    ),
                    depends_on=[observe_step],
                ),
                TaskStep(
                    step_id=f"place-{suffix}",
                    action=SemanticAction(
                        action_id=f"act-{action_index + 2:03d}",
                        action_type=ActionType.PLACE,
                        target_id=part_id,
                        parameters={"destination_id": tray_id},
                    ),
                    depends_on=[grasp_step],
                ),
            ]
        )
        action_index += 3
    return TaskGraph(task_id="task-kit-three-parts", goal=goal, steps=steps, planner="template-v2")


def build_inspection_plan(
    goal: str,
    entity_ids: Sequence[str] = DEFAULT_INSPECTION_ENTITIES,
) -> TaskGraph:
    entity_ids = _validate_entity_ids(entity_ids, "inspection")
    steps = [
        TaskStep(
            step_id=f"inspect-{entity_id.replace('_', '-')}",
            action=SemanticAction(
                action_id=f"act-{index:03d}",
                action_type=ActionType.OBSERVE,
                target_id=entity_id,
                parameters={
                    "attributes": ["presence", "identity", "orientation"],
                    "required_confidence": 0.8,
                },
            ),
        )
        for index, entity_id in enumerate(entity_ids, start=1)
    ]
    return TaskGraph(task_id="task-inspect-workpieces", goal=goal, steps=steps, planner="template-v2")


def build_clear_workspace_plan(
    goal: str,
    obstacle_id: str = "blue_cylinder",
    target_id: str = "red_block",
) -> TaskGraph:
    obstacle_id = _validate_identifier(obstacle_id, "obstacle_id")
    target_id = _validate_identifier(target_id, "target_id")
    if obstacle_id == target_id:
        raise ValueError("obstacle_id and target_id must be different")
    steps = [
        TaskStep(
            step_id="observe-obstacle",
            action=SemanticAction(action_id="act-001", action_type=ActionType.OBSERVE, target_id=obstacle_id),
        ),
        TaskStep(
            step_id="grasp-obstacle",
            action=SemanticAction(action_id="act-002", action_type=ActionType.GRASP, target_id=obstacle_id),
            depends_on=["observe-obstacle"],
        ),
        TaskStep(
            step_id="clear-obstacle",
            action=SemanticAction(
                action_id="act-003",
                action_type=ActionType.PLACE,
                target_id=obstacle_id,
                parameters={"destination_id": "staging_bin"},
            ),
            depends_on=["grasp-obstacle"],
        ),
        TaskStep(
            step_id="observe-target",
            action=SemanticAction(action_id="act-004", action_type=ActionType.OBSERVE, target_id=target_id),
            depends_on=["clear-obstacle"],
        ),
        TaskStep(
            step_id="grasp-target",
            action=SemanticAction(action_id="act-005", action_type=ActionType.GRASP, target_id=target_id),
            depends_on=["observe-target"],
        ),
        TaskStep(
            step_id="place-target",
            action=SemanticAction(
                action_id="act-006",
                action_type=ActionType.PLACE,
                target_id=target_id,
                parameters={"destination_id": "tray"},
            ),
            depends_on=["grasp-target"],
        ),
    ]
    return TaskGraph(task_id="task-clear-workspace", goal=goal, steps=steps, planner="template-v2")


def build_template_plan(goal: str, block_id: str = "red_block", tray_id: str = "tray") -> TaskGraph:
    """Route a bounded offline goal to semantic actions; never emit joint or firmware commands."""
    task_id = classify_template_task(goal)
    if task_id == "task-kit-three-parts":
        return build_kitting_plan(goal)
    if task_id == "task-inspect-workpieces":
        return build_inspection_plan(goal)
    if task_id == "task-clear-workspace":
        return build_clear_workspace_plan(goal)
    return build_place_plan(goal, block_id, tray_id)
