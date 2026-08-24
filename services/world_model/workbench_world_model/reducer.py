import json

from pydantic import BaseModel, Field
from workbench_contracts import WorldEvent, WorldEventType


class WorldState(BaseModel):
    run_id: str
    entity_locations: dict[str, str] = Field(default_factory=dict)
    entity_confidence: dict[str, float] = Field(default_factory=dict)
    entity_attributes: dict[str, dict[str, str]] = Field(default_factory=dict)
    entity_evidence_refs: dict[str, list[str]] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    applied_event_ids: list[str] = Field(default_factory=list)


def _append_entity_evidence(state: WorldState, entity_id: str, evidence_refs: list[str]) -> None:
    entity_evidence = state.entity_evidence_refs.setdefault(entity_id, [])
    entity_evidence.extend(reference for reference in evidence_refs if reference not in entity_evidence)


def _update_location(state: WorldState, entity_id: str, location: object, evidence_refs: list[str]) -> None:
    normalized_location = str(location)
    if state.entity_locations.get(entity_id) != normalized_location:
        state.entity_evidence_refs[entity_id] = list(dict.fromkeys(evidence_refs))
    else:
        _append_entity_evidence(state, entity_id, evidence_refs)
    state.entity_locations[entity_id] = normalized_location


def apply_event(state: WorldState, event: WorldEvent) -> WorldState:
    """Apply one ordered event. Re-applying an event is idempotent."""
    if event.event_id in state.applied_event_ids:
        return state

    next_state = state.model_copy(deep=True)
    next_state.applied_event_ids.append(event.event_id)
    next_state.evidence_refs.extend(event.evidence_refs)

    if event.event_type is WorldEventType.OBSERVATION:
        entity_id = event.payload.get("entity_id")
        location = event.payload.get("location")
        if entity_id:
            normalized_entity_id = str(entity_id)
            if location:
                _update_location(next_state, normalized_entity_id, location, event.evidence_refs)
            next_state.entity_confidence[normalized_entity_id] = float(event.payload.get("confidence", 0.0))
            attributes = event.payload.get("attributes")
            if isinstance(attributes, dict):
                next_state.entity_attributes[normalized_entity_id] = {
                    str(key): str(value) for key, value in attributes.items()
                }
            if not location:
                _append_entity_evidence(next_state, normalized_entity_id, event.evidence_refs)

    elif event.event_type is WorldEventType.ACTION_RESULT and event.payload.get("outcome") == "completed":
        entity_id = event.payload.get("entity_id")
        location = event.payload.get("resulting_location")
        if entity_id:
            normalized_entity_id = str(entity_id)
            if location:
                _update_location(next_state, normalized_entity_id, location, event.evidence_refs)
            else:
                _append_entity_evidence(next_state, normalized_entity_id, event.evidence_refs)

    return next_state


def _canonical_event_content(event: WorldEvent) -> str:
    return json.dumps(
        event.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _validated_event_stream(run_id: str, events: list[WorldEvent]) -> list[WorldEvent]:
    if not run_id:
        raise ValueError("run_id must be non-empty")

    content_by_event_id: dict[str, str] = {}
    event_id_by_sequence: dict[int, str] = {}
    unique_events: list[WorldEvent] = []

    for event in events:
        if event.run_id != run_id:
            raise ValueError(f"event run_id {event.run_id!r} does not match requested run_id {run_id!r}")

        event_content = _canonical_event_content(event)
        previous_content = content_by_event_id.get(event.event_id)
        if previous_content is not None:
            if previous_content != event_content:
                raise ValueError(f"event_id {event.event_id!r} is duplicated with different complete content")
            continue

        sequence_owner = event_id_by_sequence.get(event.sequence_no)
        if sequence_owner is not None:
            raise ValueError(
                f"sequence_no {event.sequence_no} is shared by event_id {sequence_owner!r} and {event.event_id!r}"
            )

        content_by_event_id[event.event_id] = event_content
        event_id_by_sequence[event.sequence_no] = event.event_id
        unique_events.append(event)

    return sorted(unique_events, key=lambda item: item.sequence_no)


def reduce_events(run_id: str, events: list[WorldEvent]) -> WorldState:
    """Preflight the full stream, fold exact duplicates, then replay by ascending sequence_no."""
    ordered_events = _validated_event_stream(run_id, events)
    state = WorldState(run_id=run_id)
    for event in ordered_events:
        state = apply_event(state, event)
    return state
