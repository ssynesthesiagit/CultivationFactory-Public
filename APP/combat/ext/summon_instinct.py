"""Instinct and directive turns for uncommanded summons (SUMMONAI1).

An uncommanded summon no longer takes Dodge.  On its own turn it acts with its
OWN stat-block actions, movement and reactions, chosen by this module's small
policy, whatever its owner's control seat (MANUAL included):

1. A standing directive (set by a command) is followed for this one turn.
2. Otherwise attack the nearest hostile it can directly perceive and reach.
3. Otherwise move toward the nearest hostile it can directly perceive, avoiding
   routes it can perceive as dangerous (hazard or reaction exposure).
4. Otherwise stay within 30 feet of its owner.

Remembered (LAST_OBSERVED) positions are never treated as live hostiles.
Every turn writes one SUMMON_TURN event saying what happened and why.

Registered on the summon_default_turn hook in combat/ext/__init__.py; core
summon lifecycle code dispatches through that hook and never imports this module.
"""

from __future__ import annotations

from typing import Any

from ..gate2_runtime_models import ActionIntent, ActorState
from ..relations import ENEMY, relation
from . import hook

INSTINCT_RANGE_FT = 30
DIRECTIVE_KINDS = ("attack", "hold", "guard", "use", "hide", "follow")
SOURCE = "system:combat.summon_instinct"


@hook("summon_default_turn")
def take_default_turn(engine: Any, actor: ActorState, behavior: str) -> None:
    """Default turn of an uncommanded summon (or one with a directive): instinct unless the directive plays out."""
    if actor.summon is None:
        return  # inert for every actor that is not a summon
    take_turn(engine, actor)


def set_directive(record: dict[str, Any], kind: str, *, target_id: str | None = None,
                  action_id: str | None = None) -> None:
    """Attach a one-turn directive from a command; the next turn of this summon follows it."""
    if kind not in DIRECTIVE_KINDS:
        raise ValueError(f"unknown summon directive: {kind}")
    if kind == "attack" and not target_id:
        raise ValueError("attack directive needs a target")
    if kind == "use" and not action_id:
        raise ValueError("use directive needs an action id")
    record["directive"] = {"kind": kind, "target_id": target_id, "action_id": action_id}


def _log(engine: Any, actor: ActorState, text: str) -> None:
    engine._append_event("SUMMON_TURN", SOURCE, actor_id=actor.entity_id, payload={"text": text})


def _hostiles(engine: Any, actor: ActorState) -> list[ActorState]:
    """Live enemies this summon directly perceives now; remembered positions do not count."""
    from ..target_knowledge import knowledge
    found = []
    for other in engine.state.actors.values():
        if not other.active or relation(engine, other, actor) != ENEMY:
            continue
        known = knowledge(engine, actor, other)
        if known is not None and known.mode == "DIRECT":
            found.append(other)
    return found


def _nearest(engine: Any, actor: ActorState, others: list[ActorState]) -> ActorState | None:
    if not others:
        return None
    return min(others, key=lambda other: (engine._distance_actor_to_actor(actor, other), other.entity_id))


def _resolve_with_intent(engine: Any, actor: ActorState, candidate: Any, resolver) -> None:
    intent = ActionIntent(intent_id=f"summon-instinct:{engine.state.event_sequence}:{actor.entity_id}",
                          decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                          state_version=candidate.state_version, actor_id=actor.entity_id,
                          target_ids=candidate.target_ids, destination=candidate.destination)
    previous = (getattr(engine, "_active_intent", None), getattr(engine, "_active_candidate", None),
                getattr(engine, "_active_action_source_id", None))
    engine._active_intent, engine._active_candidate = intent, candidate
    engine._active_action_source_id = candidate.source_definition_id
    try:
        resolver(candidate, intent)
    finally:
        engine._active_intent, engine._active_candidate, engine._active_action_source_id = previous


def _attack(engine: Any, actor: ActorState, targets: list[ActorState], why: str) -> bool:
    """Use the stat-block action that reaches the nearest of the targets it can strike now."""
    if not actor.action_available:
        return False
    ids = {t.entity_id for t in targets}
    rows = []
    for source_id in actor.action_ids:
        action = engine.action_catalog[source_id]
        for candidate in engine._action_candidates(actor, action):
            hit = [t for t in candidate.target_ids if t in ids]
            if hit:
                target = engine.state.actors[hit[0]]
                rows.append((engine._distance_actor_to_actor(actor, target), target.entity_id, source_id, candidate))
    if not rows:
        return False
    _, _, source_id, candidate = min(rows, key=lambda row: row[:3])
    action = engine.action_catalog[source_id]
    target = engine.state.actors[candidate.target_ids[0]]
    _log(engine, actor, f"{actor.display_name} {why} and attacks {target.display_name} with {action.display_name}.")
    _resolve_with_intent(engine, actor, candidate, lambda c, i: engine._resolve_action(actor, action, c, i))
    return True


def _approach(engine: Any, actor: ActorState, enemy: ActorState, why: str) -> bool:
    """Walk toward an enemy along the safest legal route that closes the distance."""
    if actor.movement_remaining_ft <= 0:
        return False
    current = engine._distance_actor_to_actor(actor, enemy)
    choices = []
    for candidate in engine._movement_candidates(actor):
        destination = candidate.destination
        if destination is None or destination == actor.position:
            continue
        if candidate.metadata.get("hazard_exposure") or candidate.metadata.get("reaction_exposure"):
            continue  # never walk into danger it can perceive
        distance = engine._distance_actor_to_actor(actor, enemy, actor_position=destination)
        if distance < current:
            choices.append(((distance, candidate.movement_cost_ft, destination.y, destination.x), candidate))
    if not choices:
        return False
    candidate = min(choices, key=lambda row: row[0])[1]
    _log(engine, actor, f"{actor.display_name} {why} and moves toward {enemy.display_name}.")
    _resolve_with_intent(engine, actor, candidate, lambda c, i: engine._resolve_movement(actor, c, i))
    return True


def _stay_near_owner(engine: Any, actor: ActorState, owner: ActorState | None) -> None:
    if owner is None or not owner.active:
        _log(engine, actor, f"{actor.display_name} has no enemy in sight and no owner to keep near; it waits.")
        return
    if engine._distance_actor_to_actor(actor, owner) <= INSTINCT_RANGE_FT:
        _log(engine, actor, f"{actor.display_name} has no enemy in sight and stays near its owner.")
        return
    from .companion_movement import move_toward_owner
    _log(engine, actor, f"{actor.display_name} has no enemy in sight and moves back within {INSTINCT_RANGE_FT} feet of its owner.")
    move_toward_owner(engine, actor, owner, INSTINCT_RANGE_FT)


def _follow_directive(engine: Any, actor: ActorState, owner: ActorState | None, directive: dict[str, Any]) -> bool:
    kind = directive["kind"]
    if kind == "hold":
        _log(engine, actor, f"{actor.display_name} follows its order: hold, and it stays where it is.")
        return True
    if kind == "attack":
        target = engine.state.actors.get(directive.get("target_id") or "")
        if target is None or not target.active:
            _log(engine, actor, f"{actor.display_name}'s ordered target is gone; it returns to instinct.")
            return False
        why = f"follows its order: attack {target.display_name}"
        if _attack(engine, actor, [target], why):
            return True
        return _approach(engine, actor, target, f"{why} (cannot reach it yet)")
    if kind == "follow":
        from .companion_movement import move_toward_owner
        _log(engine, actor, f"{actor.display_name} follows its order: follow its owner.")
        if owner is not None:
            move_toward_owner(engine, actor, owner, 5)
        return True
    # guard / use / hide need a choice the command menu does not yet offer; fall back to instinct.
    _log(engine, actor, f"{actor.display_name}'s order ({kind}) cannot be carried out here; it acts on instinct.")
    return False


def take_turn(engine: Any, actor: ActorState) -> None:
    """Run one summon turn: directive if one stands, otherwise instinct.  Clears the directive either way."""
    record = actor.summon
    directive = record.pop("directive", None) if record is not None else None
    owner = engine.state.actors.get(actor.owner_id) if actor.owner_id else None
    if directive and _follow_directive(engine, actor, owner, directive):
        return
    hostiles = _hostiles(engine, actor)
    if hostiles:
        # Reach first: strike the nearest enemy that can be struck now, before walking toward the nearest one.
        if _attack(engine, actor, hostiles, "acts on instinct"):
            return
        enemy = _nearest(engine, actor, hostiles)
        if _approach(engine, actor, enemy, "acts on instinct: no attack reaches it"):
            return
        _log(engine, actor, f"{actor.display_name} acts on instinct but cannot reach {enemy.display_name}; it holds.")
        return
    _stay_near_owner(engine, actor, owner)
