from __future__ import annotations

import copy
from typing import Any, Iterable

from .canonical import canonical_sha256
from .gate2_runtime_models import (
    CombatEvent,
    ConditionInstance,
    ConcentrationState,
    MatchState,
    ModifierInstance,
    PendingResolution,
    Position,
    RuntimeObjectState,
    TerminalResult,
    ZoneState,
)
from .gate3_models import Gate3ActorRuntimeControl, Gate3RuntimeControl, Gate3ZoneRuntimeControl

GATE3_CONTROL_KEY = "gate3_runtime_control_after"
GATE3_CONDITION_KEY = "gate3_condition_after"  #gitleaks:allow -- event-field name, not a credential
GATE3_MODIFIER_KEY = "gate3_modifier_after"
GATE3_CONCENTRATION_KEY = "gate3_concentration_after"

# Exact event surface declared by Gate 2. The reducer has an explicit disposition for each.
GATE2_EVENT_TYPES = {
    "ATTACK_ROLLED",
    "COMPANION_DEFAULT_APPLIED",
    "CONCENTRATION_ENDED",
    "CONCENTRATION_STARTED",
    "CONDITION_APPLIED",
    "CONDITION_REMOVED",
    "DAMAGE_COMMITTED",
    "DAMAGE_ROLLED",
    "ENTITY_DEFEATED",
    "HOLD_POSITION_COMMITTED",
    "INITIATIVE_ROLLED",
    "INTENT_ACCEPTED",
    "MATCH_CREATED",
    "MATCH_ENDED",
    "MODIFIER_APPLIED",
    "MODIFIER_REMOVED",
    "MOVEMENT_COMMITTED",
    "OPTIONAL_ACTION_DECLINED",
    "REACTION_DECLINED",
    "REACTION_RESOLVED",
    "REACTION_WINDOW_OPENED",
    "RESOURCE_EXPIRED",
    "RESOURCE_GAINED",
    "RESOURCE_SPENT",
    "RESOURCE_TRIGGERED",
    "ROUND_STARTED",
    "SAVE_ROLLED",
    "TEMP_HP_GRANTED",
    "TURN_ENDED",
    "TURN_STARTED",
    "ZONE_CREATED",
    "ZONE_REMOVED",
    "CHECK_ROLLED",
    "OBJECT_IGNITED",
    "ONCE_PER_TURN_CLAIMED",
    "ONCE_PER_TURN_RESET",
    "OPPORTUNITY_EXPOSURE_SUPPRESSED",
    "PASSIVE_TRIGGERED",
}

NON_MUTATING_EVENT_TYPES = {
    "ATTACK_ROLLED",
    "COMPANION_DEFAULT_APPLIED",
    "DAMAGE_ROLLED",
    "HOLD_POSITION_COMMITTED",
    "INITIATIVE_ROLLED",
    "INTENT_ACCEPTED",
    "MATCH_CREATED",
    "OPTIONAL_ACTION_DECLINED",
    "REACTION_DECLINED",
    "REACTION_WINDOW_OPENED",
    "RESOURCE_TRIGGERED",
    "SAVE_ROLLED",
    "TURN_ENDED",
    "CHECK_ROLLED",
    "OPPORTUNITY_EXPOSURE_SUPPRESSED",
}


def canonical_state_document(state: MatchState) -> dict[str, Any]:
    return state.model_dump(mode="json", by_alias=True)


def canonical_state_sha256(state: MatchState) -> str:
    return canonical_sha256(canonical_state_document(state))


def capture_runtime_control(engine: Any) -> Gate3RuntimeControl:
    state: MatchState = engine.state
    return Gate3RuntimeControl(
        round_number=state.round_number,
        current_slot_index=state.current_slot_index,
        current_actor_id=state.current_actor_id,
        pending_resolution=(
            state.pending_resolution.model_dump(mode="json")
            if state.pending_resolution is not None
            else None
        ),
        actors={
            actor_id: Gate3ActorRuntimeControl(
                position=actor.position,
                movement_remaining_ft=actor.movement_remaining_ft,
                action_available=actor.action_available,
                bonus_action_available=actor.bonus_action_available,
                reaction_available=actor.reaction_available,
                resources=dict(actor.resources),
                turn_flags=copy.deepcopy(actor.turn_flags),
                turns_started=actor.turns_started,
            )
            for actor_id, actor in sorted(state.actors.items())
        },
        zones={
            zone_id: Gate3ZoneRuntimeControl(
                active=zone.active,
                per_turn_triggered=copy.deepcopy(zone.per_turn_triggered),
            )
            for zone_id, zone in sorted(state.zones.items())
        },
        commanded_cui_this_turn=bool(getattr(engine, "_commanded_cui_this_turn", False)),
    )


def enrich_committed_events(
    events: Iterable[CombatEvent | dict[str, Any]],
    *,
    post_engine: Any,
) -> tuple[dict[str, Any], ...]:
    """Copy Gate 2 events and add only fixed typed replay-completeness fields.

    The original engine event objects are not modified. The final event receives a bounded
    runtime-control snapshot for fields that Gate 2 did not serialize as mechanical events.
    """
    docs: list[dict[str, Any]] = []
    post_state: MatchState = post_engine.state
    for raw in events:
        doc = raw.model_dump(mode="json") if isinstance(raw, CombatEvent) else copy.deepcopy(raw)
        payload = dict(doc.get("payload") or {})
        event_type = doc["event_type"]
        target_ids = tuple(doc.get("target_ids") or ())
        if event_type == "CONDITION_APPLIED" and target_ids:
            target = post_state.actors[target_ids[0]]
            instance_id = payload.get("instance_id")
            instance = target.conditions.get(instance_id) if instance_id else None
            if instance is None and payload.get("condition_id"):
                matches = [
                    row for row in target.conditions.values()
                    if row.condition_id == payload["condition_id"]
                ]
                if matches:
                    instance = sorted(matches, key=lambda row: (row.applied_sequence, row.instance_id))[-1]
            if instance is not None:
                payload[GATE3_CONDITION_KEY] = instance.model_dump(mode="json")
            else:
                # An instance applied and removed in the same transaction still receives a
                # complete typed transient representation for sequential reducer coverage.
                fallback_id = instance_id or (
                    f"gate3-transient:{payload.get('condition_id')}:{target.entity_id}:{doc['sequence']}"
                )
                payload[GATE3_CONDITION_KEY] = ConditionInstance(
                    instance_id=fallback_id,
                    condition_id=str(payload.get("condition_id", "condition:unknown")),
                    source_definition_id=doc["source_definition_id"],
                    source_actor_id=doc.get("actor_id") or "system",
                    target_id=target.entity_id,
                    stacks=int(payload.get("stacks", 1)),
                    applied_sequence=int(doc["sequence"]),
                    expires_on=payload.get("expires_on"),
                    data={},
                ).model_dump(mode="json")
        elif event_type == "MODIFIER_APPLIED" and target_ids:
            target = post_state.actors[target_ids[0]]
            modifier = target.modifiers.get(payload.get("modifier_id"))
            if modifier is not None:
                payload[GATE3_MODIFIER_KEY] = modifier.model_dump(mode="json")
            else:
                payload[GATE3_MODIFIER_KEY] = ModifierInstance(
                    modifier_id=str(payload["modifier_id"]),
                    source_definition_id=doc["source_definition_id"],
                    source_actor_id=doc.get("actor_id") or "system",
                    target_id=target.entity_id,
                    target_field=str(payload["target_field"]),
                    operation=str(payload["operation"]),
                    value=payload["value"],
                    applies_to=str(payload.get("applies_to", "ALL")),
                    expires_on=payload.get("expires_on"),
                ).model_dump(mode="json")
        elif event_type == "CONCENTRATION_STARTED" and doc.get("actor_id"):
            actor = post_state.actors[doc["actor_id"]]
            concentration = actor.concentration
            if concentration is not None:
                payload[GATE3_CONCENTRATION_KEY] = concentration.model_dump(mode="json")
            else:
                payload[GATE3_CONCENTRATION_KEY] = ConcentrationState(
                    source_definition_id=doc["source_definition_id"],
                    started_sequence=int(doc["sequence"]),
                ).model_dump(mode="json")
        elif event_type == "REACTION_RESOLVED" and doc.get("actor_id"):
            actor = post_state.actors.get(doc["actor_id"])
            if actor is not None:
                payload["gate3_reaction_available_after"] = actor.reaction_available
        doc["payload"] = payload
        docs.append(doc)
    if docs:
        payload = dict(docs[-1].get("payload") or {})
        payload[GATE3_CONTROL_KEY] = capture_runtime_control(post_engine).model_dump(
            mode="json", by_alias=True
        )
        docs[-1]["payload"] = payload
    return tuple(docs)


class Gate3EventReducer:
    """Pure typed event reducer. It never rolls or invokes Gate 2 action resolution."""

    version = "TianxiaGate3Reducer.v1"

    def __init__(self) -> None:
        self.handled_event_types = set(GATE2_EVENT_TYPES)

    def apply_events(
        self,
        state: MatchState,
        events: Iterable[dict[str, Any]],
        *,
        expected_start_sequence: int | None = None,
    ) -> MatchState:
        result = state.model_copy(deep=True)
        next_sequence = expected_start_sequence or (result.event_sequence + 1)
        for raw in events:
            event = CombatEvent.model_validate(raw)
            if event.event_type not in self.handled_event_types:
                raise ValueError(f"unsupported reducer event type: {event.event_type}")
            if event.sequence != next_sequence:
                raise ValueError(
                    f"event sequence gap: expected {next_sequence}, got {event.sequence}"
                )
            self.apply_event(result, event)
            next_sequence += 1
        return result

    def apply_event(self, state: MatchState, event: CombatEvent) -> None:
        p = event.payload
        typ = event.event_type
        target_id = event.target_ids[0] if event.target_ids else None

        if typ in NON_MUTATING_EVENT_TYPES:
            pass
        elif typ == "ROUND_STARTED":
            state.round_number = int(p["round"])
        elif typ == "TURN_STARTED":
            if event.actor_id:
                state.current_actor_id = event.actor_id
            if "slot" in p:
                state.current_slot_index = int(p["slot"])
            if "round" in p:
                state.round_number = int(p["round"])
        elif typ == "MOVEMENT_COMMITTED":
            if event.actor_id:
                actor = state.actors[event.actor_id]
                actor.position = Position.model_validate(p["destination"])
                actor.movement_remaining_ft = max(
                    0, actor.movement_remaining_ft - int(p.get("cost_ft", 0))
                )
        elif typ in {"RESOURCE_SPENT", "RESOURCE_GAINED", "RESOURCE_EXPIRED"}:
            if event.actor_id:
                actor = state.actors[event.actor_id]
                resource_id = p.get("resource_id") or event.source_definition_id
                if typ == "RESOURCE_SPENT":
                    actor.resources[resource_id] = int(p["remaining"])
                elif typ == "RESOURCE_GAINED":
                    actor.resources[resource_id] = int(p["current"])
                else:
                    actor.resources[resource_id] = int(p["after"])
        elif typ == "CONDITION_APPLIED":
            if target_id:
                condition = ConditionInstance.model_validate(p[GATE3_CONDITION_KEY])
                state.actors[target_id].conditions[condition.instance_id] = condition
        elif typ == "CONDITION_REMOVED":
            if target_id:
                instance_id = p.get("instance_id")
                if instance_id:
                    state.actors[target_id].conditions.pop(instance_id, None)
        elif typ == "MODIFIER_APPLIED":
            if target_id:
                modifier = ModifierInstance.model_validate(p[GATE3_MODIFIER_KEY])
                state.actors[target_id].modifiers[modifier.modifier_id] = modifier
        elif typ == "MODIFIER_REMOVED":
            target = state.actors[target_id] if target_id else (
                state.actors[event.actor_id] if event.actor_id else None
            )
            if target is not None and p.get("modifier_id"):
                target.modifiers.pop(p["modifier_id"], None)
        elif typ == "TEMP_HP_GRANTED":
            if target_id:
                state.actors[target_id].temporary_hp = int(p["after"])
        elif typ == "DAMAGE_COMMITTED":
            if target_id:
                target = state.actors[target_id]
                target.temporary_hp = max(
                    0, target.temporary_hp - int(p.get("temporary_hp_absorbed", 0))
                )
                target.current_hp = int(p["remaining_hp"])
        elif typ == "CONCENTRATION_STARTED":
            if event.actor_id:
                state.actors[event.actor_id].concentration = ConcentrationState.model_validate(
                    p[GATE3_CONCENTRATION_KEY]
                )
        elif typ == "CONCENTRATION_ENDED":
            if event.actor_id:
                state.actors[event.actor_id].concentration = None
        elif typ == "ZONE_CREATED":
            zone = ZoneState.model_validate(p["zone"])
            state.zones[zone.zone_id] = zone
        elif typ == "ZONE_REMOVED":
            zone = state.zones.get(p.get("zone_id"))
            if zone is not None:
                zone.active = False
        elif typ == "OBJECT_IGNITED":
            obj = RuntimeObjectState.model_validate(p["object"])
            state.objects[obj.object_id] = obj
        elif typ == "ONCE_PER_TURN_CLAIMED":
            if event.actor_id:
                scope = str(p["scope"])
                state.actors[event.actor_id].turn_flags[f"once_per_turn:{scope}"] = int(
                    p["turns_started"]
                )
        elif typ == "ONCE_PER_TURN_RESET":
            if event.actor_id:
                scope = str(p["scope"])
                state.actors[event.actor_id].turn_flags.pop(f"once_per_turn:{scope}", None)
        elif typ == "PASSIVE_TRIGGERED":
            zone_doc = p.get("zone_after")
            if zone_doc is not None:
                zone = ZoneState.model_validate(zone_doc)
                state.zones[zone.zone_id] = zone
        elif typ == "REACTION_RESOLVED":
            if event.actor_id and "gate3_reaction_available_after" in p:
                state.actors[event.actor_id].reaction_available = bool(
                    p["gate3_reaction_available_after"]
                )
        elif typ == "ENTITY_DEFEATED":
            actor_id = event.actor_id or target_id
            if actor_id:
                actor = state.actors[actor_id]
                actor.current_hp = 0
                actor.active = False
                actor.action_available = False
                actor.bonus_action_available = False
                actor.reaction_available = False
                actor.movement_remaining_ft = 0
                actor.concentration = None
        elif typ == "MATCH_ENDED":
            state.terminal_result = TerminalResult.model_validate({k: v for k, v in p.items() if k != GATE3_CONTROL_KEY})
        else:  # pragma: no cover - defensive completeness guard
            raise ValueError(f"unhandled event type: {typ}")

        state.event_sequence = event.sequence
        control_doc = p.get(GATE3_CONTROL_KEY)
        if control_doc is not None:
            self.apply_runtime_control(state, Gate3RuntimeControl.model_validate(control_doc))

    @staticmethod
    def apply_runtime_control(state: MatchState, control: Gate3RuntimeControl) -> None:
        state.round_number = control.round_number
        state.current_slot_index = control.current_slot_index
        state.current_actor_id = control.current_actor_id
        state.pending_resolution = (
            PendingResolution.model_validate(control.pending_resolution)
            if control.pending_resolution is not None
            else None
        )
        for actor_id, row in control.actors.items():
            actor = state.actors[actor_id]
            actor.position = row.position
            actor.movement_remaining_ft = row.movement_remaining_ft
            actor.action_available = row.action_available
            actor.bonus_action_available = row.bonus_action_available
            actor.reaction_available = row.reaction_available
            actor.resources = dict(row.resources)
            actor.turn_flags = copy.deepcopy(row.turn_flags)
            actor.turns_started = row.turns_started
        for zone_id, row in control.zones.items():
            zone = state.zones.get(zone_id)
            if zone is not None:
                zone.active = row.active
                zone.per_turn_triggered = copy.deepcopy(row.per_turn_triggered)


def reducer_coverage_document() -> dict[str, Any]:
    reducer = Gate3EventReducer()
    return {
        "schema": "TianxiaGate3ReplayCompletenessCoverage.v1",
        "reducer_version": reducer.version,
        "declared_gate2_event_type_count": len(GATE2_EVENT_TYPES),
        "handled_event_type_count": len(reducer.handled_event_types),
        "missing_event_types": sorted(GATE2_EVENT_TYPES - reducer.handled_event_types),
        "event_types": [
            {
                "event_type": event_type,
                "reducer_disposition": (
                    "NO_STATE_MUTATION" if event_type in NON_MUTATING_EVENT_TYPES else "TYPED_REDUCER_HANDLER"
                ),
            }
            for event_type in sorted(GATE2_EVENT_TYPES)
        ],
        "runtime_control_fields": [
            "round_number",
            "current_slot_index",
            "current_actor_id",
            "pending_resolution",
            "actor.position",
            "actor.movement_remaining_ft",
            "actor.action_available",
            "actor.bonus_action_available",
            "actor.reaction_available",
            "actor.resources",
            "actor.turn_flags",
            "actor.turns_started",
            "zone.active",
            "zone.per_turn_triggered",
            "commanded_cui_this_turn",
        ],
        "generic_state_patch_supported": False,
        "status": "PASS" if reducer.handled_event_types == GATE2_EVENT_TYPES else "FAIL",
    }
