"""Tiger-Crane Alternation: compiled ``iron_fist_rider(kind=alternation)``.

Choose after an Unarmed hit, once per current turn (including off-turn hits).
An already-Opened target grants both. Tiger wraps the actual next unarmed
Shove/Grapple save, increasing its DC; Crane resolves a legal 15-foot step
before the next Unarmed attack roll, exempting only the triggering creature's
Opportunity Attacks. Pending benefits expire at the current turn's end.
Ownership comes from the compiled action bundle, never a live character sheet.
"""
from __future__ import annotations

import copy
from typing import Any

from . import effect, hook
from .iron_fist_riders import choose, config, step

SOURCE = "TAL_IRON_FIST_TIGER_CRANE_ALTERNATION"
TIGER = "condition:typed.iron_tiger"
CRANE = "condition:typed.iron_crane"


def stamp(engine: Any) -> str:
    current = engine.state.actors[engine.state.current_actor_id]
    return f"{engine.state.round_number}:{current.entity_id}:{current.turns_started}"


def pending(engine: Any, actor: Any, name: str) -> Any:
    return next((c for c in actor.conditions.values() if c.condition_id == name
                 and c.data.get("turn") == stamp(engine)), None)


@hook("after_hit")
def alternate(ctx: Any, target: Any, kind: str) -> None:
    from .. import typed_executor as te

    if kind != "unarmed" or "alternation" not in config(ctx.engine, ctx.actor):
        return
    turn = stamp(ctx.engine)
    key = "iron_round_alternation_used"
    if ctx.actor.turn_flags.get(key) == turn:
        return
    was = te.opened_before(ctx.engine, ctx.actor.entity_id, target.entity_id)
    opened = was if was is not None else te.bears_mark(target, ctx.actor.entity_id, "Opened")
    sub = te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, ctx.damage_cache)
    picks = ["Tiger", "Crane"] if opened else choose(sub, "Tiger-Crane Alternation", ["Tiger", "Crane"])
    if not picks:
        return
    ctx.actor.turn_flags[key] = turn
    for pick in picks:
        name = TIGER if pick == "Tiger" else CRANE
        ctx.engine._remove_condition(ctx.actor, name, SOURCE)
        ctx.engine._apply_condition(ctx.actor, name, SOURCE, ctx.actor.entity_id,
                                    expires_on="END_OF_CURRENT_TURN",
                                    data={"turn": turn, "target": target.entity_id,
                                          "bonus": int(ctx.numbers.get("key_mod") or 0)})


@hook("maneuvers")
def wrap_maneuver_saves(info: dict[str, Any]) -> None:
    if SOURCE not in info["owned"]:
        return
    for action in info["actions"]:
        typed = action.parameters.get("typed") or {}
        if typed.get("unarmed_option") not in ("grapple", "shove_push", "shove_prone"):
            continue
        typed["effects"] = [{"type": "iron_tiger_save", "save": eff}
                            if eff.get("type") in ("save", "heaven_clinch_save") else eff
                            for eff in typed.get("effects") or []]


@effect("iron_tiger_save")
def tiger_save(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    held = pending(ctx.engine, ctx.actor, TIGER)
    typed = copy.deepcopy(ctx.typed)
    if held:
        typed["numbers"] = {**ctx.numbers, "save_dc": int(ctx.numbers.get("save_dc") or 10) + int(held.data["bonus"])}
        ctx.engine._remove_condition(ctx.actor, TIGER, SOURCE)
    sub = te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, typed, ctx.targets, ctx.target, ctx.damage_cache)
    te.run_effects(sub, [row["save"]])


@hook("attack_mode")
def crane_before_strike(ctx: Any, target: Any) -> None:
    # attack_mode runs before the roll for each attack, including multiattacks;
    # the core's target_check rechecks reach after this movement.
    if not any(e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
               for e in ctx.typed.get("effects") or []):
        return
    held = pending(ctx.engine, ctx.actor, CRANE)
    if held is None:
        return
    ctx.engine._remove_condition(ctx.actor, CRANE, SOURCE)
    exempt = ctx.engine.state.actors.get(held.data["target"])
    if exempt is not None:
        step(ctx, ctx.actor, exempt, 15, name="Tiger-Crane Alternation")


@hook("turn_end")
def end_windows(engine: Any, actor: Any) -> None:
    # Off-turn hits expire with that turn too, not with the striker's next turn.
    for holder in engine.state.actors.values():
        for name in (TIGER, CRANE):
            if any(c.condition_id == name for c in holder.conditions.values()):
                engine._remove_condition(holder, name, SOURCE)
