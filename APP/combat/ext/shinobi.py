"""Shinobi Subpath riders beyond combat/ext/tabik_ninpo.py (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Shinobi (Assassination, Vanishing Flesh and their Normalized Procedures). Owned rows:
``{"type": "path_passive", "kind": "shinobi", "role": "assassination"}``; Vanishing Flesh is the named state "vanishing_flesh".

Assassination    once per turn, on a hit against a creature that has not yet taken a turn in the first round, or that cannot
                 see you (you are Invisible or Hidden and it does not perceive such creatures): + 2d8 + CL of the attack's damage
                 type, then one choice (asked): it cannot take Reactions until the start of its next turn, move 10 feet without
                 provoking, Pressure-Point Strike without Stamina (tabik_ninpo.pressure_point: still once per turn), or Advantage on
                 your next Stealth check before the end of your next turn.
Vanishing Flesh  1 minute: you are Invisible; an attack or harmful activation of yours makes you visible until the end of the
                 turn (Invisible again at its end while the state lasts); the first hit during each of your turns + 3d6 of the
                 attack's type; it creates a free Shadow Afterimage (its own entry's summon) that lasts as long.
Every hook returns early for a creature without the row or state.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.shinobi.feature."
VANISH = "vanishing_flesh"
INVISIBLE = "condition:typed.invisible"


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "shinobi"}


def _vanished(engine: Any, actor: Any) -> bool:
    from .states import active

    return actor is not None and bool(active(engine, actor, VANISH))


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _cl(engine: Any, actor: Any) -> int:
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == actor.entity_id), None)
    return int((bundle or {}).get("cl") or 1)


def _unseen_by(engine: Any, actor: Any, target: Any) -> bool:
    from .. import senses

    hidden = any(c.condition_id in (INVISIBLE, "condition:typed.hidden") for c in actor.conditions.values())
    return hidden and not senses.sees_hidden(engine, target, actor)


@hook("after_hit")
def shinobi_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or not target.active or target.team_id == actor.team_id:
        return
    from .. import typed_executor as te

    weapon = ctx.typed.get("weapon") or {}
    kinds = [str(k).lower() for k in (weapon.get("damage_types") or [weapon.get("damage_type") or "bludgeoning"])]
    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={})
    if _vanished(engine, actor) and engine.state.current_actor_id == actor.entity_id and actor.turn_flags.get("_round_vanish_hit") != _stamp(engine):
        actor.turn_flags["_round_vanish_hit"] = _stamp(engine)
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 3, "sides": 6}, "damage_types": kinds,
                              "evidence": "Vanishing Flesh: the first hit this turn + 3d6"}])
    if "assassination" not in _roles(engine, actor) or actor.turn_flags.get("_round_assassination") == _stamp(engine) or not target.active:
        return
    unready = int(engine.state.round_number) == 1 and int(target.turns_started) == 0
    unseen = bool(actor.turn_flags.get("_attack_was_unseen")) or _unseen_by(engine, actor, target) \
        or target.entity_id in (actor.turn_flags.get("_vanish_unseen_by") or [])
    if not (unready or unseen):
        return
    actor.turn_flags["_round_assassination"] = _stamp(engine)
    te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "flat": _cl(engine, actor),
                          "damage_types": kinds, "evidence": "Assassination: + 2d8 + CL"}])
    if not target.active:
        return
    from .needle import ask, checkpoint_id

    labels = {"reactions": f"{target.display_name} cannot take Reactions until its next turn", "move": "Move 10 feet without provoking",
              "pressure": "Pressure-Point Strike without spending Stamina", "stealth": "Advantage on your next Stealth check"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "assassination", target.entity_id), actor, "choice:needle.assassination", list(labels),
                 labels=labels, target_id=target.entity_id, name="Assassination", prompt=f"Assassination: {target.display_name} never saw it coming. Choose one.")
    choice = picked[0] if picked else "reactions"
    if choice == "reactions":
        te.run_effects(sub, [{"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}])
    elif choice == "move":
        from .rider_movement import routes, step

        paths = routes(engine, actor, 10)
        pick = ask(engine, ctx.intent, checkpoint_id(engine, "assassination_move", actor.entity_id), actor, "choice:needle.assassination_move", sorted(paths),
                   allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=actor.entity_id,
                   prompt="Assassination: move up to 10 feet without provoking.") if paths else None
        if pick and pick[0] in paths:
            step(engine, actor, paths[pick[0]], PREFIX + "assassination")
    elif choice == "pressure":
        from .tabik_ninpo import pressure_point

        pressure_point(ctx, target)
    else:
        from .effect_durations import token

        te.run_effects(sub, [{"type": "advantage", "applies_to": "self", "on": "your next Stealth check",
                              "expires_on": token("end", actor.entity_id, int(actor.turns_started) + 1)}])


@hook("attack_mode")
def remember_unseen(ctx: Any, target: Any) -> str | None:
    """Assassination reads "you were Invisible to it" as the attack was made (the attack itself reveals you)."""
    if target is not None and "assassination" in _roles(ctx.engine, ctx.actor):
        ctx.actor.turn_flags["_attack_was_unseen"] = _unseen_by(ctx.engine, ctx.actor, target)
    return None


# -------------------------------------------------------------------------------------------------- Vanishing Flesh
@effect("vanishing_flesh")
def vanishing_flesh(ctx: Any, row: dict[str, Any]) -> None:
    ctx.engine._apply_condition(ctx.actor, INVISIBLE, PREFIX + VANISH, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Vanishing Flesh: Invisible"})


def _harmful(action: Any) -> bool:
    typed = (action.parameters or {}).get("typed") or {}
    return str(getattr(action, "target_kind", "")) in ("HOSTILE_ENTITY", "CELL") or any(
        isinstance(e, dict) and e.get("type") in ("attack", "save", "damage") for e in typed.get("effects") or [])


@hook("technique_start")
def reveal(engine: Any, actor: Any, action: Any) -> bool | None:
    if not _vanished(engine, actor) or not _harmful(action):
        return None
    # "you were Invisible to it" (Assassination): who could not see you as this action began, before it reveals you.
    actor.turn_flags["_vanish_unseen_by"] = [c.entity_id for c in engine.state.actors.values() if c.team_id != actor.team_id and _unseen_by(engine, actor, c)]
    for iid, held in list(actor.conditions.items()):
        if held.condition_id == INVISIBLE and held.source_definition_id == PREFIX + VANISH:
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", PREFIX + VANISH, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": INVISIBLE, "instance_id": iid, "reason": "REVEALED"})
            actor.turn_flags["_vanish_revealed"] = True
    return None


@hook("turn_end")
def vanish_again(engine: Any, actor: Any) -> None:
    actor.turn_flags.pop("_vanish_unseen_by", None)
    if actor.turn_flags.get("_vanish_revealed") and _vanished(engine, actor):
        actor.turn_flags.pop("_vanish_revealed", None)
        engine._apply_condition(actor, INVISIBLE, PREFIX + VANISH, actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Vanishing Flesh: Invisible"})


@hook("effect_expiring")
def vanish_ends(engine: Any, holder: Any, row: Any) -> None:
    from .states import PREFIX as STATE

    if getattr(row, "condition_id", None) != STATE + VANISH:
        return
    for iid, held in list(holder.conditions.items()):
        if held.condition_id == INVISIBLE and held.source_definition_id == PREFIX + VANISH:
            del holder.conditions[iid]
            engine._append_event("CONDITION_REMOVED", PREFIX + VANISH, actor_id=holder.entity_id, target_ids=(holder.entity_id,),
                                 payload={"condition_id": INVISIBLE, "instance_id": iid, "reason": "ENDED"})


@hook("pass_through")
def vanished_passage(engine: Any, mover: Any, occupant: Any) -> str | None:
    if mover.active and mover.team_id != occupant.team_id and _vanished(engine, mover):
        return "difficult"
    return None
