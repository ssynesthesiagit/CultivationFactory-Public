"""Brutal Momentum (Tianxia Insight): after a qualifying
completed event, the user may step up to 10 feet without
provoking Opportunity Attacks.

The printed trigger names six completed events, each read from a
receipt the engine (or a shared seam) already posts:

* "You push a hostile creature at least 10 feet" -- the general
  ``forced_movement_committed`` receipt (combat/typed_executor.py
  ``_push``), with the distance the push actually moved.
* "knock a hostile creature Prone" -- the CONDITION_APPLIED
  event for a Prone condition.
* "reduce a hostile creature to 0 Hit Points" -- the
  DAMAGE_COMMITTED event whose remaining hit points are zero.
* "break an object or structure ... destroy a barrier or
  Formation Anchor" -- the OBJECT_UPDATED event for a destroyed
  object. Ordinary objects qualify only when the saved map record has AC,
  current HP and maximum HP; an objective object may instead carry the integer
  ``component.controls_current_scene_objective = 1`` marker.
* "escape a hostile Grapple or Restrained effect" -- the shared
  ``hold_escaped`` receipt (combat/ext/hold_escapes.py), whose
  holds name the creature that owned the hold.

Every trigger must be the user's own work against a hostile
creature (or, for the escape, a hold a hostile creature owned):
a trigger an ally caused, or one that hit the user's own side,
does not count. Objects without the printed record or objective marker do
not trigger, which excludes trivial decorations. The step itself is granted movement (it does
not provoke Opportunity Attacks and does not spend the user's
own walking allowance), offered once per turn -- a second
trigger in the same turn changes nothing. The actor identity on each receipt
also prevents another creature's work from counting as the user's trigger.
"""
from __future__ import annotations

from typing import Any

from . import hook, note
from .passive_rows import row_of
from .granted_moves import destinations, commit

INSIGHT = "insight.brutal-momentum"
BLOCK = "brutal_momentum"
PRONE = ("condition:typed.prone", "condition:core.prone")
HELD = ("condition:typed.grappled", "condition:typed.restrained")
STEP_FT = 10
# The owner retains this string across other creatures' turns. Compare the
# global turn identity: "once per turn" also permits off-turn triggers.
TURN_FLAG = "brutal_momentum_used"


def owned(engine: Any, actor: Any) -> bool:
    return row_of(engine, actor.entity_id, BLOCK, "brutal_momentum") is not None


@hook("compile_block")
def compile_brutal(block: str, spec: dict[str, Any], row: dict[str, Any],
                   numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "numbers": dict(numbers)}]


# ------------------------------------------------------------------ the qualifying events
@hook("forced_movement_committed")
def pushed(engine: Any, actor: Any, target: Any, distance_ft: int, movement_kind: str, unwilling: bool = True) -> None:
    """You push a hostile creature at least 10 feet."""
    if movement_kind != "push" or not owned(engine, actor) or distance_ft < STEP_FT:
        return
    if target is None or getattr(target, "team_id", None) == actor.team_id:
        return
    offer(engine, actor, f"pushing a hostile creature {distance_ft} feet")


@hook("event")
def qualifying(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if event_type == "CONDITION_APPLIED":
        if payload.get("condition_id") not in PRONE:
            return
        applier = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
        target = engine.state.actors.get(str((kwargs.get("target_ids") or ("",))[0]))
        if applier is None or target is None or target.team_id == applier.team_id:
            return
        offer(engine, applier, "knocking a hostile creature Prone")
    elif event_type == "DAMAGE_COMMITTED":
        # "reduce a hostile creature to 0 Hit Points": the drop to
        # zero, not damage dealt to a creature already at zero.
        if payload.get("remaining_hp") != 0 or payload.get("hp_before", 1) <= 0:
            return
        attacker = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
        target = engine.state.actors.get(str((kwargs.get("target_ids") or ("",))[0]))
        if attacker is None or target is None or target.team_id == attacker.team_id:
            return
        offer(engine, attacker, "reducing a hostile creature to 0 Hit Points")
    elif event_type == "OBJECT_UPDATED":
        # A destroyed map object: an object, structure, barrier or
        # Formation Anchor with its complete AC and Hit Point record.
        obj = payload.get("object") or {}
        if not obj.get("destroyed") and int(obj.get("current_hp") or 1) > 0:
            return
        component = obj.get("component") or {}
        complete_record = all(obj.get(key) is not None
                              for key in ("ac", "current_hp", "maximum_hp"))
        objective_record = type(component.get("controls_current_scene_objective")) is int \
            and component.get("controls_current_scene_objective") == 1
        if not (complete_record or objective_record):
            return
        destroyer = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
        if destroyer is not None:
            offer(engine, destroyer, "destroying an object, barrier or Formation Anchor")


@hook("hold_escaped")
def escaped(engine: Any, record: dict[str, Any]) -> None:
    """Escape a hostile Grapple or Restrained effect."""
    escaper = engine.state.actors.get(str(record.get("holder") or ""))
    if escaper is None or not owned(engine, escaper):
        return
    for hold in record.get("holds") or []:
        if str(hold.get("condition_id") or "") not in HELD:
            continue
        owner = engine.state.actors.get(str(hold.get("owner") or ""))
        if owner is not None and owner.team_id != escaper.team_id:
            offer(engine, escaper, "escaping a hostile Grapple or Restrained effect")
            return


# ------------------------------------------------------------------ the offered step
def offer(engine: Any, actor: Any, trigger: str) -> None:
    """Offer the once-per-turn step after ``trigger`` resolved."""
    if not owned(engine, actor):
        return
    stamp = f"{engine.state.round_number}:{engine.state.current_slot_index}:{engine.state.current_actor_id}"
    if actor.turn_flags.get(TURN_FLAG) == stamp:
        return
    actor.turn_flags[TURN_FLAG] = stamp
    routes = [route for route in destinations(engine, actor, STEP_FT, lambda cell: True)
              if route[0] != actor.position]
    if not routes:
        note(engine, INSIGHT, actor,
             f"{actor.display_name} triggered Brutal Momentum ({trigger}) "
             "but had no legal destination to move to.", (actor,))
        return
    from .needle import CHOICE, ask

    ids = [f"step:{route[0].x},{route[0].y},{route[0].z}" for route in routes]
    picked = ask(engine, getattr(engine, "_active_intent", None),
                 f"brutal_momentum:{actor.entity_id}", actor, CHOICE + "brutal_momentum", ids,
                 labels={option_id: f"Move to {route[0].x},{route[0].y} ({route[2]} feet)"
                         for option_id, route in zip(ids, routes)},
                 allow_decline=True, name="Brutal Momentum", feature_id=INSIGHT,
                 prompt=(f"Brutal Momentum: after {trigger}, move up to {STEP_FT} feet "
                         "without provoking Opportunity Attacks, or stay put."))
    if not picked:
        return
    route = routes[ids.index(picked[0])]
    commit(engine, actor, route[1], f"passive:{INSIGHT}", budget_ft=STEP_FT,
           provokes=False, intent=getattr(engine, "_active_intent", None))
    note(engine, INSIGHT, actor,
         f"{actor.display_name} moves up to {STEP_FT} feet without provoking "
         f"Opportunity Attacks, after {trigger}.", (actor,))
