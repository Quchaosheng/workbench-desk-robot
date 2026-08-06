from pydantic import BaseModel, Field
from workbench_contracts import WorldEvent, WorldEventType


class WorldState(BaseModel):
    run_id: str
    entity_locations: dict[str, str] = Field(default_factory=dict)
    entity_confidence: dict[str, float] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    applied_event_ids: list[str] = Field(default_factory=list)


def apply_event(state: WorldState, event: WorldEvent) -> WorldState:
    """Apply one ordered event. Re-applying an event is idempotent."""
    if event.event_id in state.applied_event_ids:
        return state

    next_state = state.model_copy(deep=True)
    next_state.applied_event_ids.append(event.event_id)
    next_state.evidence_refs.extend(event.evidence_refs)

    if event.event_type is WorldEventType.OBSERVATION:
        entity_id = str(event.payload["entity_id"])
        next_state.entity_locations[entity_id] = str(event.payload["location"])
        next_state.entity_confidence[entity_id] = float(event.payload.get("confidence", 0.0))
    elif event.event_type is WorldEventType.ACTION_RESULT and event.payload.get("status") == "succeeded":
        entity_id = event.payload.get("entity_id")
        location = event.payload.get("resulting_location")
        if entity_id and location:
            next_state.entity_locations[str(entity_id)] = str(location)

    return next_state


def reduce_events(run_id: str, events: list[WorldEvent]) -> WorldState:
    state = WorldState(run_id=run_id)
    for event in sorted(events, key=lambda item: item.sequence_no):
        state = apply_event(state, event)
    return state
