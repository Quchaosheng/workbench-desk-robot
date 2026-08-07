import re
from collections.abc import Mapping, Sequence

from workbench_contracts import ActionType, SemanticAction, TaskGraph, TaskStep

DEFAULT_KIT_PARTS = ("red_block", "blue_cylinder", "green_gear")
DEFAULT_INSPECTION_ENTITIES = ("red_block", "blue_cylinder", "green_gear")
DEFAULT_PARCEL_ROUTES = (
    ("parcel_box", "pickup_shelf"),
    ("parcel_envelope", "pickup_shelf"),
    ("parcel_unreadable", "quarantine_bin"),
    ("parcel_damaged", "quarantine_bin"),
)
DEFAULT_PARCEL_ATTRIBUTES = {
    "parcel_box": {"label_status": "verified", "condition": "intact"},
    "parcel_envelope": {"label_status": "verified", "condition": "intact"},
    "parcel_unreadable": {"label_status": "unreadable", "condition": "intact"},
    "parcel_damaged": {"label_status": "verified", "condition": "damaged"},
}
PARCEL_POLICY_VERSION = "parcel-routing-v1"


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
    mobile_delivery = any(
        re.search(pattern, normalized)
        for pattern in (
            r"\b(go|walk|travel|navigate|drive|head)\b.*\b(parcel|package|courier|delivery|locker|lobby|downstairs)\b",
            r"\b(collect|retrieve|pick up|get)\b.*\b(parcel|package|delivery)\b.*\b(from|at)\b.*"
            r"\b(locker|lobby|downstairs|front desk)\b",
        )
    ) or any(token in normalized for token in ("去取快递", "下楼取", "快递柜取", "去拿包裹", "乘电梯取"))
    if mobile_delivery:
        raise ValueError("mobile parcel pickup requires navigation and is outside the tabletop robot boundary")
    fabricated_verification = (
        any(token in normalized for token in ("ignore", "skip", "忽略", "跳过"))
        and any(token in normalized for token in ("unreadable", "unknown label", "无法读取", "看不清"))
        and any(token in normalized for token in ("verified", "verification", "核验", "已验证"))
    )
    quarantine_bypass = bool(
        re.search(r"\b(damaged|broken)\s+(parcel|package)\b.*\b(on|to|into|in)\b.*\bpickup shelf\b", normalized)
        or re.search(r"破损.{0,10}(取件架|正常区)", normalized)
    )
    if fabricated_verification:
        raise ValueError("parcel labels must be readable evidence before they can be marked verified")
    if quarantine_bypass:
        raise ValueError("damaged parcels must be isolated and cannot be routed to pickup")
    if _matches_task_keyword(
        normalized,
        ("parcel", "parcels", "courier", "delivery", "shipment"),
        ("快递", "包裹", "分拣", "入库", "取件架"),
    ):
        return "task-sort-parcels"
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
    raise ValueError("template planner supports place, kitting, inspection, clearance, and parcel-sorting tasks")


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


def build_parcel_sorting_plan(
    goal: str,
    parcel_routes: Sequence[tuple[str, str]] = DEFAULT_PARCEL_ROUTES,
) -> TaskGraph:
    if isinstance(parcel_routes, str):
        raise ValueError("parcel routing must be a sequence of entity/destination pairs")
    routes = tuple(parcel_routes)
    if not routes or any(not isinstance(route, tuple | list) or len(route) != 2 for route in routes):
        raise ValueError("parcel routing requires entity/destination pairs")
    parcel_ids = _validate_entity_ids(tuple(route[0] for route in routes), "parcel sorting")
    destinations = tuple(_validate_identifier(route[1], "destination_id") for route in routes)
    steps: list[TaskStep] = []
    observe_steps: list[str] = []
    action_index = 1
    for parcel_id in parcel_ids:
        suffix = parcel_id.replace("_", "-")
        observe_step = f"inspect-{suffix}"
        observe_steps.append(observe_step)
        steps.append(
            TaskStep(
                step_id=observe_step,
                action=SemanticAction(
                    action_id=f"act-{action_index:03d}",
                    action_type=ActionType.OBSERVE,
                    target_id=parcel_id,
                    parameters={
                        "attributes": ["label_status", "condition"],
                        "required_confidence": 0.8,
                    },
                ),
            )
        )
        action_index += 1

    previous_route_step: str | None = None
    for parcel_id, destination_id in zip(parcel_ids, destinations, strict=True):
        suffix = parcel_id.replace("_", "-")
        grasp_step = f"grasp-{suffix}"
        route_step = f"route-{suffix}"
        dependencies = list(observe_steps)
        if previous_route_step is not None:
            dependencies.append(previous_route_step)
        steps.extend(
            [
                TaskStep(
                    step_id=grasp_step,
                    action=SemanticAction(
                        action_id=f"act-{action_index:03d}",
                        action_type=ActionType.GRASP,
                        target_id=parcel_id,
                    ),
                    depends_on=dependencies,
                ),
                TaskStep(
                    step_id=route_step,
                    action=SemanticAction(
                        action_id=f"act-{action_index + 1:03d}",
                        action_type=ActionType.PLACE,
                        target_id=parcel_id,
                        parameters={"destination_id": destination_id},
                    ),
                    depends_on=[grasp_step],
                ),
            ]
        )
        previous_route_step = route_step
        action_index += 2
    return TaskGraph(task_id="task-sort-parcels", goal=goal, steps=steps, planner="template-v3")


def _parcel_policy_decision(
    attributes: Mapping[str, str],
    pickup_shelf_id: str,
    quarantine_bin_id: str,
) -> tuple[str, str]:
    if not isinstance(attributes, Mapping):
        raise ValueError("parcel attributes must be a mapping")
    values: dict[str, str] = {}
    for key in ("label_status", "condition"):
        value = attributes.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"parcel policy requires a non-empty {key}")
        values[key] = value.strip().lower()
    if values["label_status"] == "verified" and values["condition"] == "intact":
        return pickup_shelf_id, "verified_intact"
    reasons = []
    if values["label_status"] != "verified":
        reasons.append(f"label_{values['label_status']}")
    if values["condition"] != "intact":
        reasons.append(f"condition_{values['condition']}")
    return quarantine_bin_id, "+".join(reasons)


def build_policy_routed_parcel_plan(
    goal: str,
    parcel_attributes: Mapping[str, Mapping[str, str]],
    pickup_shelf_id: str = "pickup_shelf",
    quarantine_bin_id: str = "quarantine_bin",
) -> TaskGraph:
    pickup_shelf_id = _validate_identifier(pickup_shelf_id, "pickup_shelf_id")
    quarantine_bin_id = _validate_identifier(quarantine_bin_id, "quarantine_bin_id")
    if pickup_shelf_id == quarantine_bin_id:
        raise ValueError("pickup and quarantine destinations must be different")
    if not isinstance(parcel_attributes, Mapping):
        raise ValueError("parcel_attributes must be a mapping")
    parcel_ids = _validate_entity_ids(tuple(parcel_attributes), "parcel policy")
    decisions = []
    reasons: dict[str, str] = {}
    for parcel_id in parcel_ids:
        destination_id, reason = _parcel_policy_decision(
            parcel_attributes[parcel_id], pickup_shelf_id, quarantine_bin_id
        )
        decisions.append((parcel_id, destination_id))
        reasons[parcel_id] = reason
    decisions.sort(key=lambda item: (item[1] != quarantine_bin_id, item[0]))
    plan = build_parcel_sorting_plan(goal, decisions)
    for step in plan.steps:
        if step.action.action_type is ActionType.PLACE:
            step.action.parameters.update(
                {
                    "routing_reason": reasons[step.action.target_id],
                    "policy_version": PARCEL_POLICY_VERSION,
                }
            )
    return plan.model_copy(update={"planner": "parcel-policy-v1"})


def build_template_plan(goal: str, block_id: str = "red_block", tray_id: str = "tray") -> TaskGraph:
    """Route a bounded offline goal to semantic actions; never emit joint or firmware commands."""
    task_id = classify_template_task(goal)
    if task_id == "task-kit-three-parts":
        return build_kitting_plan(goal)
    if task_id == "task-inspect-workpieces":
        return build_inspection_plan(goal)
    if task_id == "task-clear-workspace":
        return build_clear_workspace_plan(goal)
    if task_id == "task-sort-parcels":
        return build_policy_routed_parcel_plan(goal, DEFAULT_PARCEL_ATTRIBUTES)
    return build_place_plan(goal, block_id, tray_id)
