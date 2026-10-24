"""Gōruden Subpath riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Gilded Bones     owned ``path_passive`` kind ``gilded_guard``: when Stamina Guard fires, the owner picks Standard Guard (1d10 per
                 Stamina) or Gilded Guard (2d8 per Stamina) for that packet (soak_dice; asked, AI takes Gilded). Once per round,
                 if damage still reached its Hit Points after a Gilded Guard, it gains Temporary HP equal to Proficiency Bonus
                 once the packet has resolved.
Golden Sheen     ``golden_sheen``: while no armor is worn (Unarmored Defense), +1 AC and Advantage on saves against Poisoned and
                 disease (Sickened).
Golden Aura      typed as a zone following its user (inside: Necrotic Resistance and Advantage against Frightened for the
                 user and allies; triggers: Temporary HP = PB once per activation on entering or starting a turn there, a
                 hostile creature starting its turn there makes a Wisdom save) -- no code beyond the zone system.
Immortal Gold    ``golden_statue`` rides its free drop-to-zero row (with hold_at_1hp): a golden statue until the start of the
                 user's next turn (no actions, Reactions or movement; Resistance to all damage, Immunity to Poison and
                 Psychic; forced movement from a lower-CL source does nothing). At that turn's start it regains 5 x PB Hit
                 Points, the statue ends and Golden Aura starts without its cost or a use.
``no_invisible_benefit`` {"type": "no_invisible_benefit", "applies_to": "target", "duration": ...}: the creature cannot benefit
                 from Invisible for that long (Golden Aura's failed/successful save, Radiant Fist) -- the Advantage/Disadvantage
                 its Invisible condition would give is masked for attacks it makes or that target it (masked_conditions).
Every hook returns early for a creature without the owner's row or condition.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.goruden.feature."
STATUE = "condition:typed.golden_statue"
NO_BENEFIT = "condition:typed.no_invisible_benefit"
ALL = ("ACID", "BLUDGEONING", "COLD", "FIRE", "FORCE", "LIGHTNING", "NECROTIC", "PIERCING", "RADIANT", "SLASHING", "THUNDER")


def _rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "path_rider" and row.get("kind") == kind]


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}"


# ----------------------------------------------------------------------------------------------------------- Gilded Bones
@hook("soak_dice")
def gilded_guard(engine: Any, target: Any, row: dict[str, Any], spend: int, dice: Any) -> Any:
    if not _rows(engine, target, "gilded_guard") or not str(row.get("feature_id") or "").endswith("feature.stamina_guard"):
        return None
    from .needle import ask, checkpoint_id
    from .choice_prompt import action_context

    # Only packet provenance can identify nested damage reliably. The existing
    # seam covers confirmed attacks; other damage intentionally stays unnamed.
    packet = engine.damage_context()
    source_actor = engine.state.actors.get(packet.attacker_id) if packet else None
    context = action_context(engine, source_actor, packet.source_id, target) if packet and packet.target_id == target.entity_id else {
        "action_name": "", "source_definition_id": "", "action_actor_id": "", "affected_id": target.entity_id}

    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "gilded_guard", target.entity_id),
                 target, "choice:needle.gilded_guard", ["gilded", "standard"],
                 labels={"gilded": f"Gilded Guard: {2 * spend}d8 ({spend} Stamina x 2d8)", "standard": f"Standard Guard: {spend}d{dice.sides}"},
                 prompt=f"Gilded Bones: {target.display_name}'s Stamina Guard spends {spend} Stamina; choose the dice.",
                 target_id=target.entity_id, prompt_context=context)
    if picked != ["gilded"]:
        return None
    engine.__dict__.setdefault("_gilded_pending", set()).add(target.entity_id)
    return dice.model_copy(update={"count": 2 * int(spend), "sides": 8})


@hook("event")
def gilded_after(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "DAMAGE_COMMITTED":
        return
    pending = engine.__dict__.get("_gilded_pending") or set()
    for target_id in kwargs.get("target_ids") or ():
        if target_id not in pending:
            continue
        pending.discard(target_id)
        target = engine.state.actors.get(target_id)
        payload = kwargs.get("payload") or {}
        if target is None or not target.active or int(payload.get("hp_damage") or 0) <= 0:
            continue
        if target.turn_flags.get("_round_gilded_thp") == _stamp(engine):
            continue
        target.turn_flags["_round_gilded_thp"] = _stamp(engine)
        pb = int(next((row.get("pb") for row in _rows(engine, target, "gilded_guard")), 2) or 2)
        engine._grant_temp_hp(target, pb, PREFIX + "gilded_bones", target.entity_id)


# ----------------------------------------------------------------------------------------------------------- Golden Sheen
def _unarmored(engine: Any, actor: Any) -> bool:
    for bundle in getattr(engine, "typed_bundle_documents", ()) or ():
        if bundle.get("actor_id") == actor.entity_id:
            return not any(item.get("worn") and str(item.get("kind") or item.get("category") or "armor").lower() != "shield"
                           for item in (bundle.get("carrying") or {}).get("items") or [])
    return True


@hook("ac")
def sheen_ac(engine: Any, target: Any) -> int | None:
    return 1 if _rows(engine, target, "golden_sheen") and _unarmored(engine, target) else None


@hook("save")
def sheen_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if subject is None or not _rows(ctx.engine, subject, "golden_sheen") or not _unarmored(ctx.engine, subject):
        return None
    tags = {str(n).removeprefix("category:") for n in named or ()}
    return {"bonus": 0, "modes": ["ADVANTAGE"]} if {"poisoned", "sickened", "disease", "corrosion", "bodily_decay", "physical_deformation"} & tags else None


@hook("falling_damage")
def gilded_fall(engine: Any, target: Any, amount: int, fall: Any, intent: Any) -> dict[str, Any] | None:
    if not _rows(engine, target, "gilded_guard") or fall.distance_ft > 60:
        return None
    return {"amount": 0, "land_prone": True}


@hook("save")
def gilded_bone_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if subject is None or not _rows(ctx.engine, subject, "gilded_guard"):
        return None
    if {str(n).removeprefix("category:") for n in named or ()} & {"crushing", "fracture", "bone_breaking"}:
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@hook("ability_check_hazard_mode")
def golden_bodily_checks(engine: Any, actor: Any, ability: str, skill: Any, against: Any, hazards: Any) -> str | None:
    tags = {str(n).removeprefix("category:") for n in hazards or ()}
    bone = _rows(engine, actor, "gilded_guard") and tags & {"crushing", "fracture", "bone_breaking"}
    sheen = _rows(engine, actor, "golden_sheen") and _unarmored(engine, actor) and tags & {
        "disease", "poisoned", "corrosion", "bodily_decay", "physical_deformation"}
    return "ADVANTAGE" if bone or sheen else None


# ---------------------------------------------------------------------------------------------------------- Immortal Gold
@effect("golden_statue")
def golden_statue(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    engine._apply_condition(actor, STATUE, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Golden statue: Incapacitated, Speed 0, Resistance to all damage; ends at the start of its turn",
                                  "cl": int(ctx.numbers.get("cl") or 1), "pb": int(ctx.numbers.get("pb") or 2),
                                  "rule": {"counts_as_incapacitated": True, "no_actions": True, "no_reactions": True, "speed_zero": True}})
    for kind in ALL:
        engine._add_modifier(actor, ctx.source, "damage_resistance", "ADD", kind, "SELF", expires_on="UNTIL_REMOVED")
    for kind in ("POISON", "PSYCHIC"):
        engine._add_modifier(actor, ctx.source, "damage_immunity", "ADD", kind, "SELF", expires_on="UNTIL_REMOVED")


def _statue(actor: Any) -> Any:
    return next((c for c in actor.conditions.values() if c.condition_id == STATUE), None)


@hook("effect_subject_allowed")
def statue_unmoved(ctx: Any, eff: dict[str, Any], subject: Any) -> bool | None:
    """"An effect whose Source CL is lower than yours cannot move you" while a statue."""
    held = _statue(subject) if subject is not None else None
    if held is None or (eff or {}).get("type") not in ("forced_movement", "teleport", "movement"):
        return None
    from .cultivation_contests import holds_position
    if int(ctx.numbers.get("cl") or 1) < int((held.data or {}).get("cl") or 1) or holds_position(ctx.engine, subject, ctx.actor, PREFIX + "immortal_gold", source_numbers=ctx.numbers):
        return False
    return None


@hook("subject_teleport_attempt")
def statue_teleport(ctx: Any, subject: Any, start: Any, destination: Any) -> bool | None:
    return statue_unmoved(ctx, {"type": "teleport"}, subject)


@hook("turn_start")
def statue_wakes(engine: Any, actor: Any) -> None:
    held = _statue(actor)
    if held is None or not actor.active:
        return
    source = held.source_definition_id
    actor.conditions.pop(held.instance_id)
    engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"condition_id": STATUE, "instance_id": held.instance_id})
    for mid, modifier in list(actor.modifiers.items()):
        if modifier.source_definition_id == source and modifier.target_field in ("damage_resistance", "damage_immunity"):
            del actor.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"modifier_id": mid, "reason": "STATUE_ENDED"})
    from .healing_policy import ordinary_preparation
    heal = min(actor.maximum_hp - actor.current_hp, 5 * int((held.data or {}).get("pb") or 2))
    if heal > 0:
        if ordinary_preparation(engine, actor):
            from .life_state import heal_to
            heal = heal_to(engine, actor, 5 * int((held.data or {}).get("pb") or 2), source, actor.entity_id)
        else:
            before = actor.current_hp
            actor.current_hp += heal
            engine._append_event("HEALING_APPLIED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"offered": heal, "before": before, "after": actor.current_hp})
    note(engine, source, actor, f"Immortal Gold: {actor.display_name} leaves its golden statue and regains {heal} Hit Points.")
    aura = next((a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                 and ((a.parameters or {}).get("typed") or {}).get("source") == PREFIX + "golden_aura"), None)
    if aura is None:
        return
    from .. import typed_executor as te, zones

    typed = dict(aura.parameters["typed"])
    ctx = te.Context(engine, actor, aura, getattr(engine, "_active_intent", None), typed, [], None, {})
    if typed.get("zone_spec"):
        zones.create(ctx, typed["zone_spec"])
    te.run_effects(ctx, typed.get("effects") or [])
    note(engine, source, actor, f"Immortal Gold: {actor.display_name}'s Golden Aura starts without its cost.")


# ---------------------------------------------------------------------------------------------- no Invisible benefit
@effect("no_invisible_benefit")
def no_invisible_benefit(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import _default_subject, stated_expiry

    for subject in _default_subject(ctx, row, harmful=True):
        if subject.active:
            ctx.engine._remove_condition(subject, NO_BENEFIT, ctx.source)
            ctx.engine._apply_condition(subject, NO_BENEFIT, ctx.source, ctx.actor.entity_id,
                                        expires_on=stated_expiry(ctx, row, subject, condition=True) or "START_OF_TARGET_NEXT_TURN",
                                        data={"label": "Cannot benefit from Invisible"})


@hook("masked_conditions")
def invisible_masked(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    out: dict[str, set[str]] = {}
    for creature in (attacker, target):
        if creature is None or not any(c.condition_id == NO_BENEFIT for c in creature.conditions.values()):
            continue
        hidden = {iid for iid, c in creature.conditions.items() if c.condition_id in ("condition:typed.invisible", "condition:core.invisible")}
        if hidden:
            out[creature.entity_id] = hidden
    return out or None
