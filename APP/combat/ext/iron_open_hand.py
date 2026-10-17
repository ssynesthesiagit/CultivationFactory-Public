"""Open-Hand Disarm against represented held weapons, on ordinary unarmed hits.

The source-bound iron_open_hand effect is a compile-time ownership marker.
after_hit_choice offers an exact weapon, then the defender's Athletics/Acrobatics
choice. A second Unarmed Strike attack roll is contested, not checked against
AC; ties leave the object held. The hit_benefit_allowed seam replaces only
Open the Gate, whether the contest wins or loses. Opening remains independent.
Disarmed uses the existing evented owner/held_by/dropped_at weapon state.
General held objects, actual versatile grip and immediate Steal remain riders.
Size modes compare represented footprints, not unrepresented Small/Tiny sizes.
"""
from __future__ import annotations

from typing import Any

from . import effect, hook, run
from .needle import ask, checkpoint_id
from .tabik_scoundrel import skill

SOURCE = "TAL_IRON_FIST_OPEN_HAND_DISARM"
FLAG = "iron_open_hand_replaces_gate"


@effect("iron_open_hand")
def marker(ctx: Any, row: dict[str, Any]) -> None:
    pass


@hook("maneuvers")
def capture(info: dict[str, Any]) -> None:
    if SOURCE not in info["owned"]:
        return
    if not any(e.get("type") == "iron_open_hand"
               for e in info["mechanics"][SOURCE].get("effects") or []):
        return
    for action in info["actions"]:
        if ".natural." in action.source_definition_id:
            action.parameters["iron_open_hand"] = True


def held_weapons(engine: Any, target: Any) -> dict[str, tuple[Any, Any, Any]]:
    """Represented weapons in this holder's hands; retain their original owner.

    Entries are (original owner, action, Disarmed condition instance id or None).
    This deliberately does not infer arbitrary inventory objects as held.
    """
    result = {}
    unavailable = {c.data.get("disables_action") for c in target.conditions.values()}
    for aid in target.action_ids:
        action = engine.action_catalog.get(aid)
        if action is None or ".weapon." not in aid or "#" in aid or aid.endswith(".pickup"):
            continue
        if aid in unavailable or action.parameters.get("requires_held_weapon"):
            continue
        if (action.parameters.get("typed") or {}).get("weapon"):
            result[aid] = (target, action, None)
    for owner in engine.state.actors.values():
        for iid, condition in owner.conditions.items():
            aid = condition.data.get("disables_action")
            action = engine.action_catalog.get(aid)
            if condition.data.get("held_by") == target.entity_id and action is not None:
                result[aid] = (owner, action, iid)
    return result


@hook("hit_benefit_allowed")
def replace_gate(ctx: Any, target: Any, benefit: str) -> bool | None:
    if benefit == "open_the_gate" and ctx.damage_cache.get(FLAG) == target.entity_id:
        ctx.damage_cache.pop(FLAG)
        return False
    return None


@hook("attack_resolved")
def clear_replacement(ctx: Any, target: Any, hit: bool, row: dict[str, Any]) -> None:
    """No action-local substitution leaks into a later save/on-hit effect."""
    if ctx.action.parameters.get("iron_open_hand"):
        ctx.damage_cache.pop(FLAG, None)


@hook("after_hit_choice")
def on_hit(ctx: Any, target: Any, kind: str) -> None:
    from .. import typed_executor as te, typed_reactions as tr, zones, motion

    if kind != "unarmed" or not ctx.action.parameters.get("iron_open_hand"):
        return
    ctx.damage_cache.pop(FLAG, None)
    options = held_weapons(ctx.engine, target)
    if not options:
        return
    engine, actor = ctx.engine, ctx.actor
    prompt = f"Open-Hand Disarm after {ctx.action.display_name} hits {target.display_name}"

    def choose(chooser: Any, name: str, ids: list[str], **kwargs: Any) -> list[str]:
        return ask(engine, ctx.intent, checkpoint_id(engine, name, actor.entity_id, target.entity_id),
                   chooser, "choice:needle.open_hand." + name, ids, target_id=target.entity_id,
                   prompt=prompt + ": " + name, **kwargs)

    chosen = choose(actor, "Choose held weapon instead of Open the Gate", list(options),
                    labels={aid: row[1].display_name for aid, row in options.items()}, allow_decline=True)
    if len(chosen) != 1 or chosen[0] not in options:
        return
    ctx.damage_cache[FLAG] = target.entity_id
    owner, weapon, iid = options[chosen[0]]
    bonuses = {"Athletics": skill(engine, target, "Athletics", int(target.saving_throws.get("STR", 0))),
               "Acrobatics": skill(engine, target, "Acrobatics", (int(target.dexterity_score) - 10) // 2)}
    defending = choose(target, "Choose defending skill", list(bonuses),
                        preferred=[max(bonuses, key=bonuses.get)])
    if len(defending) != 1 or defending[0] not in bonuses:
        return
    name = defending[0]
    ability = "STR" if name == "Athletics" else "DEX"
    shaped = tr.on_d20_pending(engine, actor, "attack")
    properties = str(((weapon.parameters.get("typed") or {}).get("weapon") or {}).get("properties") or "").lower()
    modes = [zones.attack_mode(engine, actor, target), motion.attack_mode(engine, actor, target, melee=True, source=SOURCE),
             *shaped["modes"], *run("attack_mode", ctx, target)]
    if "two-handed" in properties:
        modes.append("DISADVANTAGE")
    for mode in modes:
        if mode in ("ADVANTAGE", "DISADVANTAGE"):
            engine._add_modifier(actor, SOURCE, "attack_mode", "SET", mode, "NEXT_ATTACK", expires_on="CONSUMED")
    bonus = int(ctx.numbers.get("attack_bonus") or 0) + int(shaped["bonus"]) + sum(int(n or 0) for n in run("attack_bonus", ctx, actor))
    mine = engine.roller.d20(modifier=bonus, actor_id=actor.entity_id, reason="ATTACK:" + SOURCE,
                             mode=engine._attack_mode(actor, target))
    engine._record_roll(mine)
    total = mine.total + engine._consume_attack_modifiers(actor)
    size = engine._footprint(target).width_cells - engine._footprint(actor).width_cells
    modes = te.check_modes(target, ability, name, engine=ctx.engine)
    # Exact-item defenses use the actual chosen object, before this check rolls.
    modes.update(m for m in run("item_check_mode", ctx, target, "disarm", chosen[0])
                 if m in ("ADVANTAGE", "DISADVANTAGE"))
    if size:
        modes.add("ADVANTAGE" if size > 0 else "DISADVANTAGE")
    modes &= {"ADVANTAGE", "DISADVANTAGE"}
    defending_ctx = te.Context(engine, target, ctx.action, ctx.intent, ctx.typed, [actor], actor)
    check_bonus = sum(int(n or 0) for n in run("check_bonus", defending_ctx, target))
    theirs = engine.roller.d20(modifier=bonuses[name] + check_bonus, actor_id=target.entity_id, reason="CHECK:" + SOURCE + ":" + name,
                               mode=next(iter(modes)) if len(modes) == 1 else "NORMAL")
    engine._record_roll(theirs)
    from . import floored

    theirs = floored(engine, target, theirs, total)
    success = total > theirs.total
    engine._append_event("CHECK_ROLLED", SOURCE, actor_id=actor.entity_id, target_ids=(target.entity_id,),
                         payload={"actor": mine.model_dump(mode="json"), "modified_total": total,
                                  "target": theirs.model_dump(mode="json"), "against": name,
                                  "roll_kind": "attack_contest", "success": success})
    if success:
        if not te.condition_immune(engine, target, "disarmed") and not tr.offer_condition_gained(engine, target, actor, "disarmed"):
            spot = target.position.model_dump(mode="json")
            if iid is None:
                engine._apply_condition(owner, te.CONDITION_PREFIX + "disarmed", SOURCE, actor.entity_id,
                                        expires_on="UNTIL_REMOVED", data={"disables_action": chosen[0], "dropped_at": spot})
            else:
                data = {k: v for k, v in owner.conditions[iid].data.items() if k != "held_by"}
                te._reapply_weapon_state(ctx, owner, iid, {**data, "dropped_at": spot})
            te._reweigh(ctx)
    tr.after_d20(engine, actor, "attack", success=success, other=target, melee=True, natural=mine.natural_result)
    (getattr(engine, "_typed_roll_outcome", None) or {}).pop(actor.entity_id, None)
