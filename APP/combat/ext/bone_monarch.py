"""Bone Monarch Subpath riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Bone Armor           a generic reaction effect may carry ``"dice_unless_types": {"types": [...], "dice": {...}}``: when the
                     damage now being taken is none of those types, the reduction rolls those dice instead (+ the row's own
                     formula, e.g. the Constitution modifier). Bone Armor: 2d8 + CON against Bludgeoning/Piercing/Slashing,
                     1d8 + CON otherwise. Any reaction row may use the key; rows without it are untouched (reaction_amount).
Marrow Regeneration  ``marrow_regeneration_choice``: after its healing the user picks one legal option -- end one Bleeding
                     whose source is no higher CL than the user's, repeat a save against Poisoned with Advantage, or repeat a
                     save against Paralyzed/Restrained caused by an ordinary physical hold (combat/ext/physical_holds.py).
                     Only options that can do something are offered; a player is asked, an AI owner takes the first. The
                     "temporary Speed reduction caused by a physical injury" option needs injury provenance and stays the GM's.
Unbroken Bones       path_passive ``critical_immunity``: a critical hit against the owner lands as a normal hit -- the extra
                     critical dice are taken off the packet (incoming_damage, the shared lane4_crit.critical_extra reading),
                     once per critical damage roll, and a PASSIVE_TRIGGERED event records critical_turned_normal.
Sovereign            ``bone_cocoon`` rides the free drop-to-zero row (with hold_at_1hp and the cocoon's Temporary HP, 5 x CL):
Reconstruction       the user is inside a bone cocoon until the start of its next turn -- no actions, Reactions or movement,
                     AC equal to its Cultivation Save DC, Resistance to Bludgeoning/Piercing/Slashing and Immunity to Poison
                     and Psychic (the cocoon is what gets hit). At the start of its next turn, if the cocoon's Temporary HP
                     remain, it emerges: Hit Points become half its maximum, it stands, Prone/Grappled/Restrained and one
                     Bleeding end, the cocoon's leftover Temporary HP go, and hostile creatures within 10 feet make a
                     Dexterity save (6d6 Piercing and Prone, or half). If the cocoon was broken, it drops to 0 Hit Points.
Everything is keyed off the owner's own rows/conditions; other characters are unaffected.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.bone_monarch.feature."
COCOON = "condition:typed.bone_cocoon"
PHYSICAL_TYPES = ("BLUDGEONING", "PIERCING", "SLASHING")


# ------------------------------------------------------------------------------------------------------------ Bone Armor
@hook("reaction_amount")
def dice_unless_types(engine: Any, actor: Any, row: dict[str, Any], eff: dict[str, Any]) -> int | None:
    rule = (eff or {}).get("dice_unless_types")
    if not rule:
        return None
    current = str(getattr(engine, "_typed_pending_damage_type", None) or "").upper()
    if current and current in {str(kind).upper() for kind in rule.get("types") or []}:
        return None  # the ordinary dice
    from ..gate2_runtime_models import DiceSpec

    numbers = row.get("numbers") or {}
    dice = rule.get("dice") or {}
    bonus = int(numbers.get("key_mod", 0)) if str(eff.get("formula") or "") == "key_ability_modifier" else 0
    roll = engine.roller.roll(DiceSpec(count=int(dice.get("count") or 1), sides=int(dice.get("sides") or 8), modifier=bonus),
                              actor_id=actor.entity_id, reason=f"REACTION:{row.get('feature_id')}", critical=False)
    engine._record_roll(roll)
    return int(roll.total)


# ---------------------------------------------------------------------------------------------------- Marrow Regeneration
def _options(ctx: Any) -> dict[str, tuple[str, Any]]:
    from . import end_effect, physical_holds
    from .repeat_saves import repeatable

    actor, out = ctx.actor, {}
    cl = int(ctx.numbers.get("cl") or 1)
    bleeding = [(iid, c) for iid, c in actor.conditions.items() if c.condition_id == "condition:typed.bleeding"
                and end_effect.source_cl(ctx, c) <= cl]
    if bleeding:
        out["bleeding"] = ("End one Bleeding affecting you", bleeding[0])
    poisoned = repeatable(actor, ("poisoned",))
    if poisoned:
        out["poisoned"] = ("Repeat the saving throw against Poisoned with Advantage", poisoned[0])
    held = [(iid, c) for iid, c in repeatable(actor, ("paralyzed", "restrained"))
            if (physical_holds.source(ctx.engine, c) or (False, None))[0]]
    if held:
        out["physical"] = ("Repeat the saving throw against a physical Paralyzed or Restrained", held[0])
    return out


@effect("marrow_regeneration_choice")
def marrow_choice(ctx: Any, row: dict[str, Any]) -> None:
    from .needle import ask, checkpoint_id
    from .repeat_saves import save_of

    options = _options(ctx)
    if not options:
        return
    engine, actor = ctx.engine, ctx.actor
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "marrow_regeneration", actor.entity_id), actor,
                 "choice:needle.marrow_regeneration", list(options), labels={key: label for key, (label, _pair) in options.items()},
                 prompt=f"Marrow Regeneration: {actor.display_name} healed; choose one more benefit.", target_id=actor.entity_id)
    if not picked:
        return
    key = picked[0]
    iid, condition = options[key][1]
    if key == "bleeding":
        if iid in actor.conditions:
            actor.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": iid})
        return
    save = save_of(condition)
    dc = int(save["dc"])
    roll = engine._roll_save(actor, str(save["ability"]).upper(), dc, ctx.source, "ADVANTAGE" if key == "poisoned" else None)
    if roll is not None and roll.total >= dc and iid in actor.conditions:
        actor.conditions.pop(iid)
        engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": condition.condition_id, "instance_id": iid, "repeat_save": True})


# --------------------------------------------------------------------------------------------------------- Unbroken Bones
def _rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "path_rider" and row.get("kind") == kind]


@hook("incoming_damage")
def critical_immunity(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str,
                      source_actor_id: str | None) -> int | None:
    rows = _rows(engine, target, "critical_immunity")
    if not rows or amount <= 0:
        return None
    from .lane4_crit import critical_extra

    rolled = next((event for event in reversed(engine.events[-25:]) if event.event_type == "DAMAGE_ROLLED"
                   and event.actor_id == source_actor_id and target.entity_id in (event.target_ids or ())), None)
    if rolled is None or any(event.event_type == "PASSIVE_TRIGGERED" and (event.payload or {}).get("critical_roll") == rolled.sequence
                             and event.actor_id == target.entity_id for event in engine.events[-25:]):
        return None
    extra = min(critical_extra(engine, target.entity_id, source_actor_id), int(amount))
    if extra <= 0:
        return None
    engine._append_event("PASSIVE_TRIGGERED", rows[0]["feature_id"], actor_id=target.entity_id, target_ids=(target.entity_id,),
                         payload={"feature_id": rows[0]["feature_id"], "critical_turned_normal": True, "damage_removed": extra,
                                  "critical_roll": rolled.sequence,
                                  "log": f"Unbroken Bones: the critical hit on {target.display_name} lands as a normal hit."})
    return extra


# ---------------------------------------------------------------------------------------------- Sovereign Reconstruction
def _cocoon(actor: Any) -> Any:
    return next((c for c in actor.conditions.values() if c.condition_id == COCOON), None)


@effect("bone_cocoon")
def bone_cocoon(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    dc = int(ctx.numbers.get("save_dc") or 10)
    engine._apply_condition(actor, COCOON, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Bone cocoon: Incapacitated, Speed 0, AC = Cultivation Save DC; emerges at the start of its turn",
                                  "ac": dc, "cl": int(ctx.numbers.get("cl") or 1), "save_dc": dc,
                                  "rule": {"counts_as_incapacitated": True, "no_actions": True, "no_reactions": True, "speed_zero": True}})
    for kind in PHYSICAL_TYPES:
        engine._add_modifier(actor, ctx.source, "damage_resistance", "ADD", kind, "SELF", expires_on="UNTIL_REMOVED")
    for kind in ("POISON", "PSYCHIC"):
        engine._add_modifier(actor, ctx.source, "damage_immunity", "ADD", kind, "SELF", expires_on="UNTIL_REMOVED")


@hook("ac")
def cocoon_ac(engine: Any, target: Any) -> int | None:
    held = _cocoon(target)
    if held is None:
        return None
    return int(held.data["ac"]) - int(target.armor_class)


def _end_cocoon(engine: Any, actor: Any, held: Any) -> None:
    source = held.source_definition_id
    actor.conditions.pop(held.instance_id, None)
    engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"condition_id": COCOON, "instance_id": held.instance_id})
    for mid, modifier in list(actor.modifiers.items()):
        if modifier.source_definition_id == source and modifier.target_field in ("damage_resistance", "damage_immunity"):
            del actor.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"modifier_id": mid, "reason": "COCOON_ENDED"})


@hook("turn_start")
def emerge(engine: Any, actor: Any) -> None:
    held = _cocoon(actor)
    if held is None or not actor.active:
        return
    intact = int(actor.temporary_hp or 0) > 0
    _end_cocoon(engine, actor, held)
    source = held.source_definition_id
    if not intact:
        note(engine, source, actor, f"Sovereign Reconstruction: the bone cocoon was broken; {actor.display_name} is at 0 Hit Points.")
        if actor.current_hp > 0:
            engine._commit_damage(actor, actor.current_hp, "FORCE", source, actor.entity_id, None, reaction_depth=3)
        return
    before = int(actor.temporary_hp)
    actor.temporary_hp = 0
    engine._append_event("TEMP_HP_GRANTED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"offered": 0, "before": before, "after": 0, "removed_by": "Sovereign Reconstruction: the cocoon opens"})
    from .. import typed_executor as te
    from .states import context

    ctx = context(engine, actor, source, [], {"pb": int(actor.proficiency_bonus or 2), "cl": int(held.data.get("cl") or 1),
                                               "save_dc": int(held.data.get("save_dc") or 10)})
    heal = max(0, actor.maximum_hp // 2 - actor.current_hp)
    if heal:
        before_hp = actor.current_hp
        actor.current_hp = min(actor.maximum_hp, actor.current_hp + heal)
        engine._append_event("HEALING_APPLIED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"offered": heal, "before": before_hp, "after": actor.current_hp})
    ended_bleeding = False
    for iid, condition in list(actor.conditions.items()):
        name = condition.condition_id.removeprefix("condition:typed.")
        if name in ("prone", "grappled", "restrained") or (name == "bleeding" and not ended_bleeding):
            ended_bleeding = ended_bleeding or name == "bleeding"
            actor.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": iid})
    foes = [other for other in sorted(engine.state.actors.values(), key=lambda a: a.entity_id)
            if other.active and other.team_id != actor.team_id and engine._distance_actor_to_actor(actor, other) <= 10]
    note(engine, source, actor, f"Sovereign Reconstruction: {actor.display_name} emerges from the bone cocoon at half its Hit Points.",
         foes)
    if foes:
        ctx.targets = foes
        ctx.target = foes[0] if len(foes) == 1 else None
        te.run_effects(ctx, [{"type": "save", "ability": "dex", "evidence": "Sovereign Reconstruction: Dexterity saving throw",
                              "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 6, "sides": 6}, "damage_types": ["piercing"]},
                                          {"type": "condition", "applies_to": "target", "condition": "prone"}],
                              "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": ["piercing"]}]}])
