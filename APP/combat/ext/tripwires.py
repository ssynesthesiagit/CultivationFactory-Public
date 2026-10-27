"""Shared "the first time it ..." detonation point for any condition that waits on a creature's next act.

A condition opts in through its ``data``: ``trips_on`` (kinds below) and ``on_trip`` (typed effect rows run against the
creature when it trips, sourced from the condition's owner with the numbers kept in ``data``: ``pb``, ``cl``,
``save_dc``). The first matching kind removes the condition and runs ``on_trip`` once, so one activation that meets
several kinds ("takes an Action, spends Cultivation Points") goes off once. Nothing here knows an ability.

Kinds and the seam that raises each (all existing):
  action, bonus_action, reaction   technique_start, after the activation's costs are paid and before its effects (an
                                   Action card, a Bonus Action card, or a Reaction taken as a card);
  reaction                         typed_reactions.reaction_paid, after payment and before effects, for every wired paid Reaction
                                   (typed windows, opportunity attacks, rider-owned Reactions); free triggers are not a
                                   Reaction taken;
  cp_spend                         the RESOURCE_SPENT event of Qi, Stamina or Resonance, so a spend outside any Action
                                   detonates right after the points are spent and before the purchase resolves.
A creature the detonation drops does not finish the activation (technique_start returns True).

Shared helper ``trip`` is used by drum_body (Internal Echo) and is the place a later "first time it moves" or "first time it
casts" wait should plug in; its docstring names its consumers.
"""

from __future__ import annotations

from typing import Any

from . import hook

TRIPS_ON = "trips_on"
CP_RESOURCES = frozenset({"resource:core.qi", "resource:core.stamina", "resource:core.resonance"})


def _is_path_resource(resource_id: Any) -> bool:
    """Recognize the stock fighters' native path pools as well as compiled core pools."""
    value = str(resource_id or "")
    return value in CP_RESOURCES or value.rsplit(".", 1)[-1] in {"qi", "stamina", "resonance"}
_ECONOMY = {"ACTION": "action", "BONUS_ACTION": "bonus_action", "REACTION": "reaction"}


def trip(engine: Any, actor: Any, kind: str) -> bool:
    """Spring every condition on ``actor`` waiting on ``kind``; True when this left the actor unable to act."""
    waiting = [c for c in actor.conditions.values() if kind in ((c.data or {}).get(TRIPS_ON) or ())]
    for held in waiting:
        if held.instance_id not in actor.conditions:
            continue  # sprung by an earlier one's effects
        actor.conditions.pop(held.instance_id)
        engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": held.condition_id, "instance_id": held.instance_id, "reason": "DETONATED"})
        source = engine.state.actors.get(held.source_actor_id)
        data = held.data or {}
        if source is None or not data.get("on_trip"):
            continue
        from .. import typed_executor as te
        from . import note
        from .states import context

        numbers = {key: int(data[key]) for key in ("pb", "cl", "save_dc") if data.get(key) is not None}
        if data.get("trip_note"):
            note(engine, held.source_definition_id, source, str(data["trip_note"]).format(name=actor.display_name), (actor,))
        te.run_effects(context(engine, source, held.source_definition_id, [actor], numbers), data["on_trip"])
    return bool(waiting) and not actor.active


@hook("technique_start")
def on_activation(engine: Any, actor: Any, action: Any) -> bool | None:
    kind = _ECONOMY.get(str(getattr(action.economy, "value", action.economy)))
    return True if kind and trip(engine, actor, kind) else None


@hook("reaction_taken")
def on_reaction(engine: Any, actor: Any, row: dict[str, Any]) -> None:
    trip(engine, actor, "reaction")


@hook("state_event")
def on_cp_spent(engine: Any, event: Any) -> None:
    payload = event.payload or {}
    if event.event_type != "RESOURCE_SPENT" or int(payload.get("amount") or 0) <= 0 or not _is_path_resource(payload.get("resource_id")):
        return
    actor = engine.state.actors.get(event.actor_id)
    if actor is not None:
        trip(engine, actor, "cp_spend")
