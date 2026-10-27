"""Primitive committed-motion notifications for teleport and motion consumers.

The native teleport executor calls this after landing and arrival settlement.
Consumers (including Athletics' distance provider) receive causal evidence, not
an instruction to create a condition. No subscriber means no persisted change.
"""
from . import ext
from .ext.ability_source import mechanic_of


def teleport_committed(ctx, subject, previous, destination, movement_event, *,
                       movement_context, unwilling, forced,
                       settlement_source_id=None, settlement_feature_id=None):
    """Publish one actual landing; all values passed to consumers are primitives."""
    if not ext.has("committed_teleport_receipt"):
        return
    state = ctx.engine.state
    receipt = {
        "receipt_id": f"{state.match_id}:movement:{movement_event.sequence}",
        "movement_sequence": int(movement_event.sequence),
        "intent_id": str(ctx.intent.intent_id) if ctx.intent is not None else "",  # ongoing effects carry no intent
        "source_definition_id": str(ctx.source if settlement_source_id is None else settlement_source_id),
        "source_feature_id": mechanic_of(ctx.action) if settlement_feature_id is None else str(settlement_feature_id),
        "actor_id": str(subject.entity_id),
        "source_actor_id": str(ctx.actor.entity_id),
        "previous_x": int(previous.x), "previous_y": int(previous.y),
        "previous_z": int(previous.z),
        "destination_x": int(destination.x), "destination_y": int(destination.y),
        "destination_z": int(destination.z),
        "distance_ft": int(ctx.engine.grid.distance_ft(previous, destination)),
        "round_number": int(state.round_number),
        "turn_actor_id": str(state.current_actor_id),
        "turn_slot": int(state.current_slot_index),
        "own_turn": int(state.current_actor_id == subject.entity_id),
        "self_teleport": int(subject.entity_id == ctx.actor.entity_id),
        "movement_context": str(movement_context),
        "willing": int(movement_context == "WILLING" and not unwilling and forced is not True
                       and (subject.entity_id == ctx.actor.entity_id or forced is False)),
    }
    ext.run_strict("committed_teleport_receipt", ctx.engine, receipt)
