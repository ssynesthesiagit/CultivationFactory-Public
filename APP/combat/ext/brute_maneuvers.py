"""Printed Brute Disarm, using the public equipment and Special Attack providers.

Only an owner of Brute Maneuvers receives these variants. The maneuvers hook
replaces that owner's legacy weapon-tag Disarm in place, preserving its id;
other spheres and weapon tags retain their own rules. No inventory entry is
inferred to be held: scoundrel_riders' public physical-possession query and
forced-drop adapter own item identity, hands, transfers and journaled drops.
"""
from __future__ import annotations

import copy
from typing import Any

from . import effect, hook, run, floored
from .needle import ask, checkpoint_id

SOURCE = "BRUTE_BASE_BRUTE_MANEUVERS"
EFFECT = "brute_disarm"


@hook("maneuvers")
def disarm_actions(info: dict[str, Any]) -> dict[str, Any] | None:
    if SOURCE not in info["owned"] or "tianxia.sphere.brute" not in info["spheres"]:
        return None
    from .weapon_actions import weapon_attacks
    from .special_attacks import REST
    from ..gate2_runtime_models import EconomyKind

    out = []
    actions = info["actions"]
    for base, typed, attack, kind in weapon_attacks(actions, info["actor_id"]):
        if attack.get("attack_kind") != "weapon" or kind in ("unarmed", "natural"):
            continue
        one = copy.deepcopy(typed)
        one.update(source=SOURCE, weapon_source_id=base.source_definition_id,
                   effects=[{"type": EFFECT, "applies_to": "target"}])
        one.pop("variant_of", None)
        params = {**copy.deepcopy(base.parameters), "typed": one, "replaces_attack": 1,
                  "expected_damage": 0, "description":
                  "Disarm: replace one attack of your Attack action. Make a weapon attack roll against the target's "
                  "chosen Athletics or Acrobatics check. On a win, drop one held item you choose; no damage. "
                  "Disadvantage against an item held in two hands; a larger target has Advantage and a smaller target Disadvantage."}
        identity = base.source_definition_id + "#disarm"
        updates = {"display_name": base.display_name + ": Disarm", "parameters": params}
        old = next((a for a in actions if a.source_definition_id == identity), None)
        if old is not None:
            old.parameters.clear()
            old.parameters.update(params)
        else:
            out.append(base.model_copy(update={**updates, "source_definition_id": identity}))
        # The canonical remaining-attack counter is shared with other Special
        # Attacks, so a second replacement consumes a slot rather than an action.
        out.append(base.model_copy(update={**updates, "source_definition_id": identity + "." + REST,
            "display_name": updates["display_name"] + " (rest of the Attack action)",
            "economy": EconomyKind.NONE, "parameters": {**params, REST: True}}))
    return {"actions": out, "rows": []}


@hook("candidate_allowed")
def held_target(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not action or not any(e.get("type") == EFFECT for e in
            ((action.parameters.get("typed") or {}).get("effects") or [])):
        return None
    from .scoundrel_riders import held_possessions
    target = engine.state.actors.get(next(iter(candidate.target_ids), ""))
    return bool(target and held_possessions(engine, target))


@effect(EFFECT, harmful=True)
def disarm(ctx: Any, row: dict[str, Any]) -> None:
    from dataclasses import replace
    for target in [ctx.target] if ctx.target is not None else ctx.targets:
        _disarm_one(replace(ctx, target=target, targets=[target]), row)


def _disarm_one(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te, typed_reactions as tr, zones, motion
    from ..ability_checks import skill_bonus, ability_modifier
    from .scoundrel_riders import held_possessions, drop_held_object
    from .hand_occupancy import occupancy

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    items = {str(item["object"]): item for item in held_possessions(engine, target)}
    if not items:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "BRUTE_DISARM_ITEM", actor.entity_id, target.entity_id),
        actor, "choice:needle.brute_disarm_item", list(items), labels={k: str(v["name"]) for k, v in items.items()},
        preferred=list(items)[:1], target_id=target.entity_id, name="Disarm: held item",
        prompt=f"Disarm against {target.display_name}: choose one held item to drop on a win. This replaces one attack and deals no damage.")
    if not picked or picked[0] not in items:
        return
    item = items[picked[0]]
    bonuses = {name: skill_bonus(engine, target, name, ability_modifier(target, ability))
               for name, ability in (("Athletics", "STR"), ("Acrobatics", "DEX"))}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "BRUTE_DISARM_SKILL", target.entity_id, actor.entity_id),
        target, "choice:needle.brute_disarm_skill", list(bonuses), preferred=[max(bonuses, key=bonuses.get)],
        labels={k: f"{'Strength' if k == 'Athletics' else 'Dexterity'} ({k}) {v:+d}" for k, v in bonuses.items()},
        target_id=target.entity_id, name="Resist Disarm",
        prompt=f"{actor.display_name} uses Disarm against {target.display_name}'s {item['name']}: choose Athletics or Acrobatics against the weapon attack roll.")
    skill = picked[0] if picked and picked[0] in bonuses else max(bonuses, key=bonuses.get)
    ability = "STR" if skill == "Athletics" else "DEX"
    identity = str(item.get("weapon_action") or "")
    token = "weapon:" + identity if identity else "shield:" + str(item["key"])
    hands = sum(token in occupants for occupants in occupancy(engine, target).values())
    shaped = tr.on_d20_pending(engine, actor, "attack")
    modes = [zones.attack_mode(engine, actor, target),
             motion.attack_mode(engine, actor, target, melee=ctx.action.range_ft <= 10, source=ctx.source),
             *shaped["modes"], *run("attack_mode", ctx, target)]
    if hands >= 2:
        modes.append("DISADVANTAGE")
    for mode in modes:
        if mode in ("ADVANTAGE", "DISADVANTAGE"):
            engine._add_modifier(actor, ctx.source, "attack_mode", "SET", mode, "NEXT_ATTACK", expires_on="CONSUMED")
    bonus = int(ctx.numbers.get("attack_bonus") or 0) + int(shaped["bonus"]) + sum(int(n or 0) for n in run("attack_bonus", ctx, actor))
    with engine.d20_scope({"kind": "attack", "actor_id": actor.entity_id, "target_id": target.entity_id, "source_id": ctx.source}):
        mine = engine.roller.d20(modifier=bonus, actor_id=actor.entity_id, reason="ATTACK:" + ctx.source,
                                 mode=engine._attack_mode(actor, target))
        engine._record_roll(mine)
    total = mine.total + engine._consume_attack_modifiers(actor)
    size = te.size_rank(ctx, target, "subject", {}) - te.size_rank(ctx, actor, "actor", {})
    modes = set(te.check_modes(target, ability, skill, engine=engine, against_creature=actor))
    modes.update(m for m in run("item_check_mode", ctx, target, "disarm", identity or str(item["object"]))
                 if m in ("ADVANTAGE", "DISADVANTAGE"))
    if size:
        modes.add("ADVANTAGE" if size > 0 else "DISADVANTAGE")
    from dataclasses import replace
    defending = replace(ctx, actor=target, target=actor, targets=[actor])
    bonus = bonuses[skill] + sum(int(n or 0) for n in run("check_bonus", defending, target))
    with engine.d20_scope({"kind": "check", "actor_id": target.entity_id, "target_id": actor.entity_id,
                           "ability": ability, "skill": skill, "source_id": ctx.source}):
        theirs = engine.roller.d20(modifier=bonus, actor_id=target.entity_id, reason="CHECK:" + ctx.source + ":" + skill,
                                   mode=next(iter(modes)) if len(modes) == 1 else "NORMAL")
        engine._record_roll(theirs)
    theirs = floored(engine, target, theirs, total)
    success = total > theirs.total
    engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(target.entity_id,),
        payload={"actor": mine.model_dump(mode="json"), "modified_total": total, "target": theirs.model_dump(mode="json"),
                 "target_skill": skill, "against": skill, "roll_kind": "attack_contest", "contest": "disarm",
                 "object_id": item["object"], "success": success})
    if success:
        drop_held_object(engine, target, item, source=ctx.source, by=actor)
    tr.after_d20(engine, actor, "attack", success=success, other=target,
                 melee=(ctx.typed.get("weapon") or {}).get("attack_delivery") != "ranged", natural=mine.natural_result)
    (getattr(engine, "_typed_roll_outcome", None) or {}).pop(actor.entity_id, None)
