"""Movement helper shared by data-driven companion policies in combat/ext/summon_policies.py.

It selects the closest legal reachable anchor and records the move through the
standard MOVEMENT_COMMITTED reducer event.
"""

from __future__ import annotations

from typing import Any

from ..gate2_runtime_models import ActionIntent


def move_toward_owner(engine: Any, creature: Any, owner: Any, within_ft: int) -> None:
    """Move as far toward the owner as possible within this turn's legal movement budget."""
    if within_ft < 0 or engine._distance_actor_to_actor(owner, creature) <= within_ft:
        return
    current_distance = engine._distance_actor_to_actor(creature, owner)
    candidates = engine._movement_candidates(creature)
    choices = []
    for candidate in candidates:
        destination = candidate.destination
        if destination is None or destination == creature.position:
            continue
        distance = engine._distance_actor_to_actor(creature, owner, actor_position=destination)
        if distance >= current_distance:
            continue
        choices.append(((distance > within_ft, distance, candidate.movement_cost_ft, destination.y, destination.x), candidate))
    if not choices:
        return
    candidate = min(choices, key=lambda row: row[0])[1]
    outer_intent = getattr(engine, "_active_intent", None)
    intent = ActionIntent(intent_id=f"companion-move:{engine.state.event_sequence}:{creature.entity_id}",
                          decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                          state_version=candidate.state_version, actor_id=creature.entity_id,
                          target_ids=candidate.target_ids, destination=candidate.destination,
                          # The follow move is part of the owner's end-turn
                          # transaction. Preserve its answered reaction choices
                          # so commit/replay resolve exactly like the preview.
                          reaction_decisions=getattr(outer_intent, "reaction_decisions", ()))
    previous = (getattr(engine, "_active_intent", None), getattr(engine, "_active_candidate", None),
                getattr(engine, "_active_action_source_id", None))
    engine._active_intent, engine._active_candidate = intent, candidate
    engine._active_action_source_id = candidate.source_definition_id
    try:
        engine._resolve_movement(creature, candidate, intent)
    finally:
        engine._active_intent, engine._active_candidate, engine._active_action_source_id = previous
