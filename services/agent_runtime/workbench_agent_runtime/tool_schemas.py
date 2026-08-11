"""Parameter schemas for the six semantic-action tools.

Each tool is defined by its ActionType, a set of required and optional parameter
keys, and the expected Python type for each parameter value.  The schemas here
are the single source of truth consumed by ToolRegistry; A5 (Policy Validator)
reads the same registry to build its whitelist.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from workbench_contracts import ActionType

# ---------------------------------------------------------------------------
# type tags used by the registry
# ---------------------------------------------------------------------------
# str, int, float, bool and list are used as-is.
# We represent "any" with a sentinel so the registry can tell the difference
# between a deliberately permissive param and a missing definition.
_ANY = object()


# ---------------------------------------------------------------------------
# per-tool definitions
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: dict[ActionType, dict[str, object]] = {
    ActionType.OBSERVE: {
        "description": "Observe the workspace or a specific entity.  No required "
        "parameters; provide target_id via the SemanticAction field.",
        "required_params": frozenset[str](),
        "optional_params": frozenset({"required_confidence", "attributes"}),
        "param_types": {
            "required_confidence": float,
            "attributes": list,
        },
    },
    ActionType.GRASP: {
        "description": "Grasp a known entity identified by target_id.  "
        "target_id is validated at the SemanticAction level.",
        "required_params": frozenset[str](),
        "optional_params": frozenset[str](),
        "param_types": {},
    },
    ActionType.PLACE: {
        "description": "Place a grasped entity into a destination.  "
        "destination_id is required in parameters.  Routing, capacity and "
        "manifest fields are optional and used by policy-driven task types.",
        "required_params": frozenset({"destination_id"}),
        "optional_params": frozenset(
            {
                "routing_reason",
                "routing_priority",
                "policy_version",
                "identity_guard",
                "manifest_guard",
                "manifest_id",
                "destination_capacity",
                "destination_occupancy_after",
                "destination_remaining_after",
            }
        ),
        "param_types": {
            "destination_id": str,
            "routing_reason": str,
            "routing_priority": str,
            "policy_version": str,
            "identity_guard": str,
            "manifest_guard": str,
            "manifest_id": str,
            "destination_capacity": int,
            "destination_occupancy_after": int,
            "destination_remaining_after": int,
        },
    },
    ActionType.ASK_CONFIRM: {
        "description": "Ask a human operator for confirmation before proceeding.",
        "required_params": frozenset({"question"}),
        "optional_params": frozenset({"timeout_s"}),
        "param_types": {
            "question": str,
            "timeout_s": int,
        },
    },
    ActionType.EXPRESS: {
        "description": "Express an emotion state (idle / thinking / uncertain / pleased).",
        "required_params": frozenset({"emotion_state"}),
        "optional_params": frozenset({"duration_ms"}),
        "param_types": {
            "emotion_state": str,  # enum-checked by the registry
            "duration_ms": int,
        },
    },
    ActionType.STOP: {
        "description": "Safe-stop the current run.  No required parameters.",
        "required_params": frozenset[str](),
        "optional_params": frozenset({"reason"}),
        "param_types": {
            "reason": str,
        },
    },
}

# Additional per-tool runtime constraints that are not captured by
# required/optional/type alone.
EXPRESS_EMOTION_STATES: frozenset[str] = frozenset(
    {"idle", "thinking", "uncertain", "pleased"}
)

# Allow-list for observe attributes (used by policy-based planners).
KNOWN_OBSERVE_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "presence",
        "identity",
        "orientation",
        "label_status",
        "condition",
        "tracking_id",
        "barcode",
        "parcel_uid",
    }
)
