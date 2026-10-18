"""Jigoku's five source-owned native combat consumers.

The bundled Body R8 parent and normalized procedures govern these hooks.
Hell-Tempered answers only completed positive Fire HP damage, with explicit
source history and the printed Reaction/Stamina/round/cap restrictions.
Pain Eater owns one captured-CL mark, adds PB to the confirmed unarmed packet,
and exposes all four printed benefits with native movement and expiry.
Flame Fist preserves per-strike type choice; Brand owns its separate activation,
captured CL/DC, persistent pulse/save state and any-adjacent extinguish Action.
Hellwalker reads actual active areas and sealed provenance, preserves all four
start-turn choices, and ignores only its owner's listed-source obscuration.
Rage's state, separate round responses and unarmed rider use captured numbers;
all actual endings apply Exhaustion, Hell-Signaled and the cooling lockout.

The companion jigoku_procedures module owns acquisition, scars, world inputs,
meaningful-scene allowance, resource recovery, rites and elapsed Rage clocks.
Native helpers own damage, defenses, reactions, legal movement and persistence.
The existing choice-owner contract preserves manual choices on AI turns.
No owned row/state means no grant or source effect. See docs/jigoku_runtime.md
for public contracts and the lane report for unfinished acceptance boundaries.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.jigoku.feature."
RAGE = "asura_s_rage"
MARK = "condition:typed.pain_eater_mark"
COOLED = "condition:typed.eat_the_flame_spent"
NEXT_UNARMED = "condition:typed.hellwalker_unarmed_advantage"
NO_DIFFICULT = "condition:typed.hellwalker_ignores_difficult"
PENDING_START = "condition:typed.jigoku_hellwalker_start_choice"
START_CHOICE = "system:combat.jigoku_hellwalker_start_choice"
PENDING_FLAME = "condition:typed.jigoku_initial_flame"
FLAME_CHOICE = "system:combat.jigoku_initial_flame_choice"



def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "jigoku"}


def _rage_condition(engine: Any, actor: Any) -> Any:
    """The Asura's Rage condition this creature is holding, or None: the one gate both the combat hook
    (condition_immune) and the Defences card (defense_description) read."""
    from .states import active

    return active(engine, actor, RAGE) if actor is not None else None


def _raging(engine: Any, actor: Any) -> bool:
    return _rage_condition(engine, actor) is not None


def _pb(actor: Any) -> int:
    return int(getattr(actor, "proficiency_bonus", 0) or 2)


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}:{engine.state.actors[engine.state.current_actor_id].turns_started}"


def _unarmed(ctx: Any) -> bool:
    return ".natural." in ctx.source or any(isinstance(e, dict) and e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                                            for e in ctx.typed.get("effects") or [])


def _context(engine: Any, owner: Any, target: Any, intent: Any, feature: str, name: str) -> Any:
    from .. import typed_executor as te
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    action = ActionDefinition(source_definition_id=PREFIX + feature, display_name=name, owner_id=owner.entity_id, economy=EconomyKind.NONE,
                              resolution_kind="TYPED", target_kind="HOSTILE_ENTITY")
    row = next((r for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(owner.entity_id, []) if r.get("block") == "path_rider" and r.get("feature_id") == PREFIX + feature), {})
    from .needle import numbers_of
    actual = numbers_of(engine, owner)
    numbers = {"pb": _pb(owner), "cl": int(row.get("cl") or actual.get("cl") or 1), "save_dc": int(row.get("save_dc") or actual.get("save_dc") or 10)}
    return te.Context(engine, owner, action, intent, {"effects": [], "numbers": numbers, "duration": {"kind": "instant"}, "riders": []},
                      [target], target, {})


def _rage_context(engine: Any,owner: Any,target: Any,intent: Any) -> Any:
    """All responses retain the bodily state's original Source CL and numbers."""
    from dataclasses import replace
    ctx=_context(engine,owner,target,intent,RAGE,"Asura's Rage")
    held=_rage_condition(engine,owner)
    numbers=(held.data.get('numbers') or {}) if held else {}
    return replace(ctx,typed={**ctx.typed,'numbers':{**ctx.numbers,**numbers}})


def _move(ctx: Any, mover: Any, feet: int, choice_id: str, name: str, *, source: str | None = None) -> bool:
    from .needle import ask, checkpoint_id
    from ..granted_movement import routes, resolve_path, Route
    from .needle import cell_id

    paths = {cell_id(cell): Route(tuple(path), mode) for cell, (path, cost, mode) in routes(ctx.engine, mover, feet).items()}
    if not paths:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "jigoku_move", mover.entity_id), mover, choice_id, sorted(paths),
                 allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=mover.entity_id,
                 prompt=f"{name}: {mover.display_name} may move up to {feet} feet without provoking Opportunity Attacks.")
    if picked and picked[0] in paths:
        return resolve_path(ctx.engine, mover, paths[picked[0]], source or ctx.source,
                            feet=feet, intent=ctx.intent, provokes=False) > 0
    return False




# ------------------------------------------------------------------------------------ after hostile typed damage
@hook("damage_dealt")
def after_hostile_damage(ctx: Any, target: Any, amount: int) -> None:
    engine, other = ctx.engine, ctx.actor
    if target is None or not target.active or amount <= 0:
        return
    roles = _roles(engine, target)
    raging = _raging(engine, target)
    if not roles and not raging:
        return
    fire_hp = sum(int(p.get("hp_damage") or 0) for p in ctx.damage_packets if str(p.get("damage_type", "")).upper() == "FIRE")
    if other is None or other is target:
        from .jigoku_procedures import qualifying_map_hazard
        if "eat_the_flame" in roles and fire_hp > 0 and qualifying_map_hazard(engine,target) and _fresh_flame_source(engine,target):
            if ctx.intent is None and getattr(engine,'_active_intent',None) is None:
                _defer_initial_flame(engine,target,ctx.damage_packets,ctx.source,other.entity_id if other else '')
            else:_eat_the_flame(ctx,target)
        return
    if "eat_the_flame" in roles and fire_hp > 0 and target.reaction_available and int(target.resources.get("resource:core.stamina",0)) > 0 and _qualifying(ctx, target) and _fresh_flame_source(engine, target):
        _eat_the_flame(ctx, target)
    if "pain_eater" in roles and other.active and _qualifying(ctx, target):
        _pain_mark(ctx, target, other)
    if raging and _qualifying(ctx, target):
        _rage_answers(ctx, target, other)


def _eat_the_flame(ctx: Any, owner: Any) -> None:
    engine = ctx.engine
    # Fire packets of this same hit: an attached rider's Fire can land before the primary packet.
    taken = sum(int(packet.get("hp_damage") or 0) for packet in ctx.damage_packets
                if str(packet.get("damage_type") or "").upper() == "FIRE")
    from ..typed_reactions import can_use_reaction
    if taken < 1 or not can_use_reaction(engine, owner, ctx.actor, {"feature_id": PREFIX + "hell_tempered"}):
        return
    if any(c.condition_id == COOLED for c in owner.conditions.values()) or owner.turn_flags.get("_round_eat_the_flame") == int(engine.state.round_number):
        return
    if int(owner.resources.get("resource:core.stamina", 0) or 0) < 1:
        return
    from .needle import ask, checkpoint_id

    gain = min(taken, 2 * _pb(owner))
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "eat_the_flame", owner.entity_id), owner, "choice:needle.eat_the_flame", ["eat"],
                 labels={"eat": f"Reaction and 1 Stamina: gain {gain} Temporary Hit Points"}, allow_decline=True, target_id=owner.entity_id,
                 name="Eat the Flame", prompt=f"Eat the Flame: {owner.display_name} took {taken} Fire damage.")
    if not picked:
        return
    from .. import typed_executor as te
    from .. import typed_reactions

    with activation(engine, owner, PREFIX + "hell_tempered"):
        typed_reactions.open_reaction(engine, {"feature_id": PREFIX + "hell_tempered"}, owner, (ctx.actor.entity_id,), "DAMAGE_COMMITTED")
        typed_reactions.spend_reaction(engine, owner, {"feature_id": PREFIX + "hell_tempered"})
        owner.turn_flags["_round_eat_the_flame"] = int(engine.state.round_number)
        engine._spend_resource(owner, "resource:core.stamina", 1, PREFIX + "hell_tempered")
        from ..activation_payments import reaction_completed
        if not reaction_completed(engine, owner, PREFIX + "hell_tempered"):
            return
        te.run_effects(_context(engine, owner, owner, ctx.intent, "hell_tempered", "Eat the Flame"),
                       [{"type": "temp_hp", "applies_to": "self", "flat": gain, "evidence": "Eat the Flame"}])


def _pain_mark(ctx: Any, owner: Any, other: Any) -> None:
    engine = ctx.engine
    if owner.turn_flags.get("_round_pain_eater") == int(engine.state.round_number):
        return
    from .effect_durations import token
    from .needle import ask, checkpoint_id

    picked = ask(engine, ctx.intent, checkpoint_id(engine, "pain_eater", other.entity_id), owner, "choice:needle.pain_eater", ["mark"],
                 labels={"mark": f"Mark {other.display_name} until the end of your next turn"}, allow_decline=True, target_id=other.entity_id,
                 name="Pain Eater", prompt=f"Pain Eater: {other.display_name} damaged {owner.display_name}.")
    if not picked:
        return
    owner.turn_flags["_round_pain_eater"] = int(engine.state.round_number)
    for creature in engine.state.actors.values():  # one mark of yours at a time
        for iid, held in list(creature.conditions.items()):
            if held.condition_id == MARK and held.source_actor_id == owner.entity_id:
                del creature.conditions[iid]
                engine._append_event("CONDITION_REMOVED", PREFIX + "pain_eater", actor_id=owner.entity_id, target_ids=(creature.entity_id,),
                                     payload={"condition_id": MARK, "instance_id": iid, "reason": "REPLACED"})
    engine._apply_condition(other, MARK, PREFIX + "pain_eater", owner.entity_id, expires_on=token("end", owner.entity_id, int(owner.turns_started) + 1),
                            data={"label": f"Pain Eater: marked by {owner.display_name}", "source_cl": int(_context(engine, owner, other, ctx.intent, "pain_eater", "Pain Eater").numbers["cl"]), "numbers": dict(_context(engine, owner, other, ctx.intent, "pain_eater", "Pain Eater").numbers)})


def _rage_move(ctx: Any, owner: Any) -> None:
    engine = ctx.engine
    round_no = int(engine.state.round_number)
    if owner.turn_flags.get("_round_asura_move") != round_no:
        with activation(engine, owner, PREFIX + RAGE):
            sub = _rage_context(engine, owner, owner, ctx.intent)
            if _move(sub, owner, 10, "choice:needle.asura_move", "Asura's Rage"):
                owner.turn_flags["_round_asura_move"] = round_no


def _rage_strike(ctx: Any, owner: Any, other: Any) -> None:
    engine = ctx.engine
    round_no = int(engine.state.round_number)
    from ..typed_reactions import can_use_reaction
    if ctx.typed.get("granted_attack") or ctx.typed.get("reaction_attack") or owner.turn_flags.get("_round_asura_strike") == round_no or not can_use_reaction(engine, owner, other, {"feature_id": PREFIX + RAGE}) or not other.active:
        return
    from ..typed_reactions import attack_reaches
    from .needle import ask, checkpoint_id

    if not attack_reaches(engine, owner, other, {"attack_kind": "unarmed"}):
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "asura_strike", other.entity_id), owner, "choice:needle.asura_strike", ["strike"],
                 labels={"strike": f"Reaction: one unarmed strike against {other.display_name}"}, allow_decline=True, target_id=other.entity_id,
                 name="Asura's Rage", prompt=f"Asura's Rage: {other.display_name} damaged {owner.display_name} within your reach.")
    if not picked:
        return
    from .. import typed_executor as te
    from .. import typed_reactions

    with activation(engine, owner, PREFIX + RAGE):
        owner.turn_flags["_round_asura_strike"] = round_no
        typed_reactions.open_reaction(engine, {"feature_id": PREFIX + RAGE}, owner, (other.entity_id,), "DAMAGE_COMMITTED")
        typed_reactions.spend_reaction(engine, owner, {"feature_id": PREFIX + RAGE})
        from ..activation_payments import reaction_completed
        if not reaction_completed(engine, owner, PREFIX + RAGE):
            return
        strike = {"type": "attack", "attack_kind": "unarmed", "count": 1, "granted_attack_root": True}
        from dataclasses import replace
        sub = typed_reactions.triggered_context(engine, owner, other, {"feature_id": PREFIX + RAGE, "name": "Asura's Rage", "effects": [strike],
            "numbers": dict((_rage_condition(engine, owner).data or {}).get("numbers") or {})}, ctx.intent)
        te.run_effects(replace(sub, typed={**sub.typed, "granted_attack": True}), [strike])


# ------------------------------------------------------------------------------------------ unarmed hits
@hook("after_hit")
def jigoku_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if kind != "unarmed" or target is None:
        return
    from .. import typed_executor as te

    pending = ctx.damage_cache.pop("jigoku_pain_benefit:" + target.entity_id, None)
    if pending is None:
        return
    numbers=ctx.damage_cache.pop("jigoku_pain_numbers:"+target.entity_id,{})
    sub = ctx.on_hit_context(target, action=ctx.action, typed={**ctx.typed,"numbers":{**ctx.numbers,**numbers}}, damage_cache={})
    from .needle import ask, checkpoint_id

    labels = {"temp_hp": f"Gain {_pb(actor)} Temporary Hit Points", "move": "Move 5 feet without provoking",
              "save": "Advantage on your next saving throw before your next turn", "no_reactions": f"{target.display_name} cannot take Reactions until its next turn"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "pain_eater_hit", target.entity_id), actor, "choice:needle.pain_eater_benefit", list(labels),
                 labels=labels, target_id=target.entity_id, name="Pain Eater", prompt=f"Pain Eater: your marked foe {target.display_name} is hit. Choose one.")
    choice = picked[0] if picked else "temp_hp"
    if choice == "temp_hp":
        te.run_effects(sub, [{"type": "temp_hp", "applies_to": "self", "formula": "pb"}])
    elif choice == "move":
        _move(sub, actor, 5, "choice:needle.pain_eater_move", "Pain Eater", source=PREFIX + "pain_eater")
    elif choice == "save":
        te.run_effects(sub, [{"type": "advantage", "applies_to": "self", "on": "your next Strength, Dexterity, Constitution, Intelligence, Wisdom or Charisma saving throw", "expires_on": "START_OF_SELF_NEXT_TURN"}])
    elif target.active:
        te.run_effects(sub, [{"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}])


@effect("burning_brand")
def burning_brand(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    target = ctx.target
    if target is None or not target.active:
        return
    dice = 2 if int(ctx.numbers.get("cl") or 1) >= 17 else 1
    ctx = _context(ctx.engine, ctx.actor, target, ctx.intent, "flame_fist", "Burning Brand")
    te.run_effects(ctx, [{"type": "save", "ability": "con", "evidence": "Burning Brand: Constitution saving throw",
                          "on_fail": [{"type": "condition", "applies_to": "target", "condition": "burning", "expires_on": "UNTIL_REMOVED",
                                       "repeat_save": {"ability": "CON", "when": "end"},
                                       "condition_data": {"burn": 0, "brand_dice": dice, "source_cl": int(ctx.numbers.get("cl") or 1), "brand_save_dc": int(ctx.numbers.get("save_dc") or 10), "label": f"Burning Brand: {dice}d8 Fire at the start of each turn"}}],
                          "on_success": [{"type": "damage", "applies_to": "target", "dice": {"count": dice, "sides": 8}, "damage_types": ["fire"]}]}])


@hook("turn_start_choice")
def brand_burns(engine: Any, actor: Any) -> None:
    """A Burning Brand's start-of-turn packet (the table's Burn deals none: its "burn" is 0)."""
    from .. import typed_executor as te

    for held in [c for c in actor.conditions.values() if c.condition_id == "condition:typed.burning" and (c.data or {}).get("brand_dice")]:
        owner = engine.state.actors.get(held.source_actor_id)
        if owner is None or not actor.active:
            continue

        from dataclasses import replace
        sub = _context(engine, owner, actor, getattr(engine, "_active_intent", None), "flame_fist", "Burning Brand")
        sub = replace(sub, typed={**sub.typed, "numbers": {**sub.numbers, "cl": int(held.data.get("source_cl") or sub.numbers["cl"]),
            "save_dc": int(held.data.get("brand_save_dc") or sub.numbers["save_dc"])}})
        te.run_effects(sub,
                       [{"type": "damage", "applies_to": "target", "dice": {"count": int(held.data["brand_dice"]), "sides": 8}, "damage_types": ["fire"],
                         "evidence": "Burning Brand"}])


# ------------------------------------------------------------------------------------------------- Hellwalker
def _hellish_cells(engine: Any, actor: Any) -> bool:
    from .. import zones, zone_sources
    near = {(x + dx, y + dy, z + dz) for x,y,z in engine._actor_volume(actor)
            for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1,0,1)}
    for zone in zones.typed_zones(engine):
        profile = zone_sources.of(zone) or {}
        tags = {str(t).lower() for t in profile.get("source_tags", ())}
        if zone.owner_id == zones.MAP_OWNER:
            from .jigoku_procedures import hazard_fact
            fact = hazard_fact(engine, actor, zone.zone_id)
            native_rules = zones.terrain_rules().get("terrains", {})
            physical = [native_rules.get(str(kind), {}) for kind in zone.trigger_profile.get("terrain", ())]
            if fact and not fact['staged'] and not fact['cosmetic'] and any(
                    row.get('material') in {'fire','smoke','lava','magma','ash'}
                    and (row.get('obscured') or row.get('difficult') or row.get('enter_start')) for row in physical):
                if any((c.x,c.y,c.z) in near for c in zone.affected_cells):
                    return True
        if zone.active and tags.intersection({"active_flame", "fire", "smoke", "magma", "ash_terrain", "ash", "hostile_fire"}) and not tags.intersection({"cosmetic", "staged"}) and any((c.x, c.y, c.z) in near for c in zone.affected_cells):
            if _active_environment(engine,actor,zone,profile):return True
    return False


@hook("turn_start_choice")
def hellwalker(engine: Any, actor: Any) -> None:
    if "hellwalker" not in _roles(engine, actor) or not actor.active or not _hellish_cells(engine, actor):
        return
    if actor.turn_flags.get("_round_hellwalker_start") == int(actor.turns_started):
        return
    actor.turn_flags["_round_hellwalker_start"] = int(actor.turns_started)
    if getattr(engine, "_active_intent", None) is None:
        engine._apply_condition(actor, PENDING_START, PREFIX + "hellwalker", actor.entity_id,
            expires_on="END_OF_CURRENT_TURN", data={"label":"Hellwalker: choose your start-of-turn benefit", "turn":int(actor.turns_started)})
        return
    _hellwalker_benefit(engine, actor)


def _hellwalker_benefit(engine: Any, actor: Any) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id
    intent = getattr(engine, "_active_intent", None)
    labels = {"temp_hp": f"Gain {_pb(actor)} Temporary Hit Points", "advantage": "Advantage on your next unarmed attack this turn",
              "move": "Move 10 feet without provoking", "terrain": "Ignore Difficult Terrain this turn"}
    picked = ask(engine, intent, checkpoint_id(engine, "hellwalker", actor.entity_id), actor, "choice:needle.hellwalker", list(labels), labels=labels,
                 target_id=actor.entity_id, name="Hellwalker", prompt="Hellwalker: you start your turn in or beside fire, smoke, magma or ash. Choose one.")
    choice = picked[0] if picked else "temp_hp"
    ctx = _context(engine, actor, actor, intent, "hellwalker", "Hellwalker")
    if choice == "temp_hp":
        te.run_effects(ctx, [{"type": "temp_hp", "applies_to": "self", "formula": "pb"}])
    elif choice == "move":
        _move(ctx, actor, 10, "choice:needle.hellwalker_move", "Hellwalker")
    else:
        engine._apply_condition(actor, NEXT_UNARMED if choice == "advantage" else NO_DIFFICULT, PREFIX + "hellwalker", actor.entity_id,
                                expires_on="END_OF_CURRENT_TURN",
                                data={"label": labels[choice], "source_cl":int(ctx.numbers["cl"])})


@hook("difficult_exempt")
def hellwalker_terrain(engine: Any, actor: Any) -> set[tuple[int, int]] | None:
    if not any(c.condition_id == NO_DIFFICULT for c in actor.conditions.values()):
        return None
    return {(x, y) for x in range(engine.grid.width) for y in range(engine.grid.height)}


# ----------------------------------------------------------------------------------------------- Asura's Rage
@hook("attack_mode")
def unarmed_advantage(ctx: Any, target: Any) -> str | None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or not _unarmed(ctx):
        return None
    held = next((c for c in actor.conditions.values() if c.condition_id == NEXT_UNARMED), None)
    if held is not None:
        actor.conditions.pop(held.instance_id)
        engine._append_event("CONDITION_REMOVED", PREFIX + "hellwalker", actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": NEXT_UNARMED, "instance_id": held.instance_id, "reason": "CONSUMED"})
        return "ADVANTAGE"
    return "ADVANTAGE" if _raging(engine, actor) else None


@hook("attack_damage_types")
def rage_types(ctx: Any, attack: Any, kinds: Any) -> list[str] | None:
    if not _raging(ctx.engine, ctx.actor) or not _unarmed(ctx):
        return None
    return list(dict.fromkeys([*(str(k).upper() for k in kinds or []), "BLUDGEONING", "FIRE", "NECROTIC"]))


@hook("condition_immune")
def rage_fearless(engine: Any, actor: Any, name: str) -> bool | None:
    return True if str(name).lower() == "frightened" and _raging(engine, actor) else None


@hook("defense_description")
def rage_fearless_description(engine: Any, target: Any) -> list[dict[str, Any]] | None:
    """A raging Hellwalker's Frightened immunity, as the Defences card names it.

    The same gate the condition_immune hook reads (the Rage condition itself), so the card can list an
    immunity combat really applies. Pure: it names the condition it already finds and asks nothing of the
    fight."""
    rage = _rage_condition(engine, target)
    if rage is None:
        return None
    return [{"feature_id": rage.source_definition_id, "conditions": ["frightened"],
             "expires_on": rage.expires_on, "note": "only while raging"}]


@hook("state_event")
def rage_ends(engine: Any, event: Any) -> None:
    """All evented state removals, including early ending, own the aftermath once."""
    from .states import PREFIX as STATE
    payload = event.payload or {}
    if event.event_type in ('ACTOR_DEFEATED', 'LIFE_STATE_CHANGED'):
        for actor_id in event.target_ids:
            holder = engine.state.actors.get(actor_id)
            if holder is not None and holder.current_hp <= 0:
                rage = _rage_condition(engine, holder)
                if rage is not None:
                    engine._remove_condition(holder, rage.condition_id, PREFIX + RAGE + ':unconscious')
        return
    if event.event_type != "CONDITION_REMOVED" or payload.get("condition_id") not in (
            STATE + RAGE, "condition:typed.suppressed.state." + RAGE):
        return
    for actor_id in event.target_ids:
        holder = engine.state.actors.get(actor_id)
        if holder is None:
            continue
        ended = holder.turn_flags.setdefault("_round_asura_ended_instances", [])
        iid = payload.get("instance_id")
        if not iid or iid in ended:
            continue
        ended.append(iid)
        from . import forged_exhaustion
        from .directional_signals import SIGNAL
        from .jigoku_procedures import SCENE_CONDITION
        ledger=next((c for c in holder.conditions.values() if c.condition_id==SCENE_CONDITION),None)
        captured=(ledger.data.get('rage_source_cl') if ledger else None)
        authority={'source_cl':int(captured)} if captured else {}
        forged_exhaustion.set_level(engine, holder, forged_exhaustion.level(holder) + 1, PREFIX + RAGE + ":aftermath")
        if not any(c.condition_id == COOLED for c in holder.conditions.values()):
            engine._apply_condition(holder, COOLED, PREFIX + RAGE + ":aftermath", holder.entity_id, expires_on="UNTIL_REMOVED",
                data={"label": "Eat the Flame is unavailable until a cooling rite after the scene", **authority})
        if not any(c.condition_id == SIGNAL and c.source_definition_id.removesuffix(":aftermath").removesuffix(".aftermath") == PREFIX + RAGE for c in holder.conditions.values()):
            engine._apply_condition(holder, SIGNAL, PREFIX + RAGE + ":aftermath", holder.entity_id, expires_on="UNTIL_REMOVED",
                data={"label": "Hell-Signaled", "audience": ["infernal", "daemonic"], "retain_removal_data":1, **authority})
        note(engine, PREFIX + RAGE, holder, f"Asura's Rage ends: {holder.display_name} gains 1 Exhaustion level.")


def _qualifying(ctx: Any, owner: Any) -> bool:
    """Mechanical hostility/CL plus the attacker's explicit subjective intent.

    Team membership alone cannot establish willingness, staged violence or a
    weakened blow. The actual attacker owns this declaration, including when a
    human controls it on somebody else's turn. Automatic attackers use source history sealed from native owner input;
    no hidden target fact is consulted.
    """
    from ..fact_consent_admission import admit_choice, combat_records
    from .needle import numbers_of
    other = ctx.actor
    if getattr(other, 'owner_id', None) == owner.entity_id:
        return False
    if int(numbers_of(ctx.engine, other).get('cl', 1)) < int(numbers_of(ctx.engine, owner).get('cl', 1))-5:
        return False
    scope = str(ctx.intent.intent_id) + ':' + owner.entity_id + ':' + ctx.source
    records = combat_records(ctx.engine, other, source=PREFIX+'hell_tempered', kind='hostile_intent', scope=scope)
    if records:
        return records[-1]['value'] == 'genuine'
    from .jigoku_procedures import known_hostility, hostility_fact
    history = hostility_fact(ctx.engine, other)
    if history and (owner.entity_id not in history['hostile_to'] or any(history[k] for k in ('cooperative','staged','weakened','captured','revived','controlled'))):
        return False
    known = known_hostility(ctx.engine, other, owner)
    record = admit_choice(ctx, other, PREFIX+'hell_tempered', 'hostile_intent', scope,
        ['genuine','cooperative','weakened','staged','captured','revived','controlled'],
        labels={'genuine':'A genuine hostile attack', 'cooperative':'Cooperative or willing damage',
                'weakened':'Deliberately weakened damage', 'staged':'A staged interaction or repeated hazard',
                'captured':'Deliberately captured to generate resources','revived':'Repeatedly revived to generate resources',
                'controlled':'Controlled or created by the defender or a willing ally'},
        prompt=f'{other.display_name}: was {ctx.action.display_name} against {owner.display_name} genuine hostile damage? Cooperative, weakened and staged damage cannot fuel Jigoku.',
        expires_on='END_OF_CURRENT_TURN',readers=(owner.entity_id,),automatic_options=['genuine'] if known else [])
    return record is not None and record['value']=='genuine'


@hook('damage_packet_selection')
def hit_packet(ctx: Any, target: Any, packet_kinds: Any) -> None:
    """Confirmed hit: Pain Eater joins the strike's resolved damage type.

    The shared packet selection checkpoint runs after hit confirmation and
    before defenses. Benefits remain after the complete strike's damage.
    """
    from .condition_events import drop_condition
    if not _unarmed(ctx) or target is None:return
    from .needle import ask,checkpoint_id
    raging=_raging(ctx.engine,ctx.actor) and ctx.actor.turn_flags.get('_round_asura_hit')!=_stamp(ctx.engine)
    rage_type=None
    if raging:
        picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'asura_damage_type',ctx.actor.entity_id,target.entity_id),
            ctx.actor,'choice:needle.asura_damage_type',['FIRE','NECROTIC'],
            labels={'FIRE':'Add 3d6 Fire damage to this unarmed strike','NECROTIC':'Add 3d6 Necrotic damage to this unarmed strike'},
            name="Asura's Rage",target_id=target.entity_id,prompt=f"Asura's Rage: choose the additional damage type against {target.display_name}. No additional Stamina is spent.")
        rage_type=picked[0] if picked else 'FIRE'
    held=next((c for c in target.conditions.values() if c.condition_id==MARK and c.source_actor_id==ctx.actor.entity_id),None)
    rage_bonus=0
    if held is not None:
        drop_condition(ctx.engine,target,held.instance_id,PREFIX+'pain_eater')
        ctx.damage_cache['jigoku_pain_benefit:'+target.entity_id]=1
        ctx.damage_cache['jigoku_pain_numbers:'+target.entity_id]=dict(held.data.get('numbers') or {})
        spec=ctx.attack_defense_spec
        primary=str(spec.get('damage_type') or '').upper()
        # packet_kinds comes from the resolved strike, including independent
        # riders such as Burning Weapon; Rage contributes its chosen rider too.
        # The executor may report the base weapon packet as the abstract
        # WEAPON kind. Pain Eater selects a resolved damage type, so retain the
        # concrete strike type and never offer that placeholder to the player.
        kinds=list(dict.fromkeys([primary, *(str(getattr(k, 'value', k)).upper()
                                               for k in (packet_kinds or ())
                                               if k and str(getattr(k, 'value', k)).upper() != 'WEAPON'),
                                  *((rage_type,) if rage_type else [])]))
        selected=primary
        if len(kinds)>1:
            choice=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'pain_damage_type',ctx.actor.entity_id,target.entity_id),
                ctx.actor,'choice:needle.pain_eater_damage_type',kinds,
                labels={k:f'Add Proficiency Bonus damage to the strike’s {k.title()} packet' for k in kinds},
                name='Pain Eater',target_id=target.entity_id,prompt=f'Pain Eater: this unarmed strike deals several types to {target.display_name}. Choose the type of its additional Proficiency Bonus damage.')
            selected=choice[0] if choice else primary
        bonus=int((held.data.get('numbers') or {}).get('pb') or _pb(ctx.actor))
        if selected==primary:
            dice=spec.get('damage')
            if dice is not None:spec['damage']=dice.model_copy(update={'modifier':dice.modifier+bonus})
        elif raging and selected==rage_type:
            rage_bonus=bonus
        else:
            from ..typed_executor import run_effects
            run_effects(ctx.on_hit_context(target),[{'type':'extra_damage','applies_to':'target','flat':bonus,
                'damage_types':[selected.lower()],'damage_label':'Pain Eater','evidence':'Pain Eater'}])
    if raging:
        from dataclasses import replace
        from ..typed_executor import run_effects
        ctx.actor.turn_flags['_round_asura_hit']=_stamp(ctx.engine)
        state=_rage_condition(ctx.engine,ctx.actor)
        numbers=(state.data.get('numbers') or {}) if state else {}
        sub=replace(ctx.on_hit_context(target,typed={**ctx.typed,'numbers':{**ctx.numbers,**numbers}},damage_cache={}),defer_damage_notifications=True)
        run_effects(sub,[{'type':'extra_damage','applies_to':'target','dice':{'count':3,'sides':6},'flat':rage_bonus,
                          'damage_types':[rage_type.lower()],'damage_label':"Asura's Rage",'evidence':"Asura's Rage"}])


@hook('zone_obscuration_ignored')
def hellwalker_sight(engine: Any, zone: Any, viewer: Any, seen: Any) -> bool | None:
    if 'hellwalker' not in _roles(engine,viewer) or zone.owner_id!=viewer.entity_id:return None
    from ..zone_sources import of
    profile=of(zone) or {}
    tags={str(t).lower() for t in profile.get('source_tags',())}
    allowed=profile.get('sphere_id') in {'tianxia.sphere.'+s for s in ('ash','fire','magma','daemonic_cultivation')}
    allowed=allowed or str(profile.get('mechanic_id','')).startswith('tianxia.subpath.body.jigoku.')
    return True if allowed and tags.intersection({'smoke','active_flame','fire','darkness'}) else None


@hook('attack_damage_final')
def native_damage(engine: Any, attacker: Any, target: Any, provenance: Any, intent: Any) -> None:
    """Read the native settled attack, not an intermediate damage event."""
    action=engine.action_catalog.get(provenance.source_id)
    if action is None or (action.parameters or {}).get('typed') or intent is None:return
    from dataclasses import replace
    # Exact attack roll boundary, never an arbitrary recent-event window.
    roll=next((e for e in reversed(engine.events) if e.event_type=='ATTACK_ROLLED' and e.payload.get('roll_id')==provenance.roll_id),None)
    if roll is None:return
    packets=tuple(dict(e.payload) for e in engine.events if e.sequence>roll.sequence and e.event_type=='DAMAGE_COMMITTED'
                  and e.actor_id==attacker.entity_id and e.source_definition_id==provenance.source_id and target.entity_id in e.target_ids)
    amount=sum(int(p.get('hp_damage',0))+int(p.get('temporary_hp_absorbed',0)) for p in packets)
    if amount:
        ctx=_context(engine,attacker,target,intent,'hell_tempered',action.display_name)
        ctx=replace(ctx,action=action,damage_packets=packets)
        after_hostile_damage(ctx,target,amount)


@hook('damage_defenses')
def rage_resistance(engine: Any, actor: Any, kind: str, typed: Any, source_actor_id: Any) -> list[dict] | None:
    if _raging(engine,actor) and str(kind).upper() not in ('FORCE','RADIANT','VOID'):
        return [{'feature_id':PREFIX+RAGE,'kind':'resistance','damage_types':[str(kind).upper()]}]
    return None


def _fresh_flame_source(engine: Any, owner: Any) -> bool:
    from .damage_delivery import key, event
    from .condition_events import drop_condition
    kind,source=key(engine)
    occurrence=event(engine)
    if kind not in ('area','trap') or not source or not occurrence:return True
    cid='condition:typed.jigoku_fire_exposure'
    held=next((c for c in owner.conditions.values() if c.condition_id==cid),None)
    prior=held.data.get('sources',{}) if held else {}
    # Older records without activation identities are conservatively spent.
    seen=dict(prior) if isinstance(prior,dict) else {key:'' for key in prior}
    # Painted area IDs are local to an actual map. Cast/placed zone IDs are
    # local to one native match; neither index alone is a world-wide identity.
    if source.startswith('zone:map:'):
        board=getattr(engine,'battlefield_document',{}) or {}
        identity='map:'+str(board.get('stable_id') or board.get('battlefield_id') or 'unidentified')+'|'+source
    elif source.startswith(('zone:typed:','zone:placed:')):
        identity='match:'+str(engine.state.match_id)+'|'+source
    else:identity=source
    if identity in seen:return seen[identity]==occurrence
    if source in seen:return seen[source]==occurrence  # conservative legacy receipts
    if held:drop_condition(engine,owner,held.instance_id,PREFIX+'hell_tempered')
    engine._apply_condition(owner,cid,PREFIX+'hell_tempered',owner.entity_id,expires_on='UNTIL_REMOVED',
        data={'sources':{**seen,identity:occurrence},'label':'Previously encountered Fire sources cannot fuel Eat the Flame again'})
    return True


@hook('state_event')
def record_flame_exposure(engine: Any, event: Any) -> None:
    if event.event_type!='DAMAGE_COMMITTED' or str(event.payload.get('damage_type','')).upper()!='FIRE':return
    for aid in event.target_ids:
        owner=engine.state.actors.get(aid)
        if owner is not None and 'eat_the_flame' in _roles(engine,owner):
            _fresh_flame_source(engine,owner)


def _rage_answers(ctx: Any, owner: Any, other: Any) -> None:
    from .needle import ask,checkpoint_id
    from ..typed_reactions import can_use_reaction,attack_reaches
    engine=ctx.engine;round_no=int(engine.state.round_number)
    both=(owner.turn_flags.get('_round_asura_move')!=round_no and owner.turn_flags.get('_round_asura_strike')!=round_no
          and not ctx.typed.get('granted_attack') and not ctx.typed.get('reaction_attack')
          and can_use_reaction(engine,owner,other,{'feature_id':PREFIX+RAGE})
          and attack_reaches(engine,owner,other,{'attack_kind':'unarmed'}))
    order=ask(engine,ctx.intent,checkpoint_id(engine,'asura_response_order',owner.entity_id,other.entity_id),owner,
        'choice:needle.asura_response_order',['strike_first','move_first'],labels={
            'strike_first':'Choose the Reaction strike first, then movement', 'move_first':'Choose movement first, then recheck reach for the Reaction strike'},
        prompt=f"Asura's Rage: {other.display_name} damaged {owner.display_name}. Choose the order of your two separate responses.") if both else []
    if order and order[0]=='strike_first':
        _rage_strike(ctx,owner,other)
        if owner.active:_rage_move(ctx,owner)
    else:
        _rage_move(ctx,owner)
        if owner.active:_rage_strike(ctx,owner,other)


@hook('damage_packet_resolved')
def native_ongoing_damage(engine: Any, target: Any, receipt: dict, source: str, source_actor_id: str, intent: Any) -> None:
    """Whole native burns/hazards that have no typed/attack completion caller."""
    if target is None or not (_roles(engine,target) or _raging(engine,target)):return
    if engine.damage_context() is not None:return
    frame=getattr(engine,'_typed_damage_packet',None) or {}
    from .damage_delivery import frame as delivery_frame
    if (frame.get('actor'),frame.get('target'))==(source_actor_id,target.entity_id) and delivery_frame(engine)['identity']==source:return
    intent=intent or getattr(engine,'_active_intent',None)
    attacker=engine.state.actors.get(source_actor_id)
    if intent is None:
        from .jigoku_procedures import qualifying_map_hazard
        if ('eat_the_flame' in _roles(engine,target) and str(receipt.get('damage_type','')).upper()=='FIRE'
                and int(receipt.get('hp_damage',0))>0 and qualifying_map_hazard(engine,target) and _fresh_flame_source(engine,target)):
            _defer_initial_flame(engine,target,(receipt,),source,source_actor_id)
        return
    if attacker is None:
        from .jigoku_procedures import qualifying_map_hazard
        if not qualifying_map_hazard(engine,target):return
        attacker=target
    amount=int(receipt.get('hp_damage',0))+int(receipt.get('temporary_hp_absorbed',0))
    if amount<=0:return
    from dataclasses import replace
    from ..gate2_runtime_models import ActionDefinition
    action=engine.action_catalog.get(source) or ActionDefinition(source_definition_id=source,
        display_name='Ongoing damage',owner_id=attacker.entity_id,economy='NONE',resolution_kind='TYPED',target_kind='HOSTILE_ENTITY')
    ctx=_context(engine,attacker,target,intent,'hell_tempered',action.display_name)
    after_hostile_damage(replace(ctx,action=action,damage_packets=(dict(receipt),)),target,amount)


@hook('match_start')
def start_choice_action(engine: Any) -> None:
    from ..gate2_runtime_models import ActionDefinition
    roles={str(r.get('role')) for rows in engine.typed_passive_rows.values() for r in rows if r.get('block')=='path_rider' and r.get('kind')=='jigoku'}
    if 'eat_the_flame' in roles:
        engine.action_catalog[FLAME_CHOICE]=ActionDefinition(source_definition_id=FLAME_CHOICE,
            display_name='Eat the Flame: answer resolved Fire damage',owner_id='*',economy='NONE',resolution_kind='TYPED',target_kind='SELF',
            parameters={'free_primary':True,'typed':{'effects':[{'type':'jigoku_initial_flame_choice'}],'numbers':{},'riders':[]},
                'description':'After the complete Fire packet, choose whether to use your Reaction and 1 Stamina for Temporary Hit Points, capped at twice Proficiency Bonus.'})
    if 'hellwalker' not in roles:return
    engine.action_catalog[START_CHOICE]=ActionDefinition(source_definition_id=START_CHOICE,
        display_name='Hellwalker: choose your start-of-turn benefit',owner_id='*',economy='NONE',resolution_kind='TYPED',target_kind='SELF',
        parameters={'free_primary':True,'typed':{'effects':[{'type':'jigoku_hellwalker_start_choice'}],'numbers':{},'riders':[]},
            'description':'Choose one: move 10 feet without Opportunity Attacks, gain Advantage on your next unarmed attack this turn, gain Temporary Hit Points equal to your Proficiency Bonus, or ignore difficult terrain this turn. No action or Stamina is spent.'})


@hook('additional_actions')
def offer_start_choice(engine: Any,actor: Any) -> list[str] | None:
    rows=[]
    if FLAME_CHOICE in engine.action_catalog and any(c.condition_id==PENDING_FLAME for a in engine.state.actors.values() for c in a.conditions.values()):rows.append(FLAME_CHOICE)
    if START_CHOICE in engine.action_catalog and any(c.condition_id==PENDING_START for c in actor.conditions.values()):rows.append(START_CHOICE)
    return rows or None


@hook('candidate_allowed')
def start_choice_required(engine: Any,actor: Any,candidate: Any,action: Any) -> bool | None:
    if any(c.condition_id==PENDING_FLAME for a in engine.state.actors.values() for c in a.conditions.values()):return candidate.source_definition_id==FLAME_CHOICE
    if candidate.source_definition_id==FLAME_CHOICE:return False
    pending=any(c.condition_id==PENDING_START for c in actor.conditions.values())
    if pending:return candidate.source_definition_id==START_CHOICE
    if candidate.source_definition_id==START_CHOICE:return False
    return None


@effect('jigoku_hellwalker_start_choice')
def resolve_start_choice(ctx: Any,row: dict) -> None:
    held=next((c for c in ctx.actor.conditions.values() if c.condition_id==PENDING_START),None)
    if held is None or held.data.get('turn')!=int(ctx.actor.turns_started):return
    if _hellish_cells(ctx.engine,ctx.actor):_hellwalker_benefit(ctx.engine,ctx.actor)
    from .condition_events import drop_condition
    drop_condition(ctx.engine,ctx.actor,held.instance_id,PREFIX+'hellwalker')


@effect('jigoku_initial_flame_choice')
def initial_flame_choice(ctx: Any,row: dict) -> None:
    import json
    from dataclasses import replace
    from .condition_events import drop_condition
    for owner in ctx.engine.state.actors.values():
        for held in list(owner.conditions.values()):
            if held.condition_id!=PENDING_FLAME:continue
            data=held.data
            drop_condition(ctx.engine,owner,held.instance_id,PREFIX+'hell_tempered')
            attacker=ctx.engine.state.actors.get(data['source_actor']) or owner
            sub=_context(ctx.engine,attacker,owner,ctx.intent,'hell_tempered','Eat the Flame')
            _eat_the_flame(replace(sub,damage_packets=tuple(json.loads(data['receipts']))),owner)


def _defer_initial_flame(engine: Any,target: Any,packets: Any,source: str,actor: str) -> None:
    """Retain real committed packets until the first accepted intent can ask."""
    import json
    engine._apply_condition(target,PENDING_FLAME,PREFIX+'hell_tempered',target.entity_id,expires_on='END_OF_CURRENT_TURN',
        data={'receipts':json.dumps(list(packets),sort_keys=True),'source':source,'source_actor':actor,
              'label':'Eat the Flame: choose whether to answer the just-resolved Fire damage'})


def _active_environment(engine: Any,owner: Any,zone: Any,profile: dict) -> bool:
    """Explicit creator intent, not appearance or damage-name inference."""
    creator=engine.state.actors.get(zone.owner_id)
    if creator is None:return False
    from .jigoku_procedures import hazard_fact
    fact=hazard_fact(engine,creator,'source:'+str(profile.get('mechanic_id','')))
    if fact and (fact['staged'] or fact['cosmetic']):return False
    intent=getattr(engine,'_active_intent',None)
    if intent is None:return True  # The pending opening action collects the choice.
    from ..fact_consent_admission import combat_records,admit_choice
    scope=zone.zone_id+':'+owner.entity_id
    records=combat_records(engine,creator,source=PREFIX+'hellwalker',kind='environment_intent',scope=scope)
    record=records[-1] if records else admit_choice(
        _context(engine,creator,owner,intent,'hellwalker','Hellwalker environmental area'),creator,
        PREFIX+'hellwalker','environment_intent',scope,['active','staged','cosmetic'],
        labels={'active':'An active, mechanically present area that was not staged for this benefit',
                'staged':'A staged effect used to generate the benefit','cosmetic':'A harmless cosmetic effect'},
        prompt=f"Hellwalker: {owner.display_name} is beside {creator.display_name}'s environmental area. Was this actual area staged or merely cosmetic?",
        expires_on='UNTIL_REMOVED',readers=(owner.entity_id,),automatic_options=['active'] if fact else [])
    return bool(record and record['value']=='active')


@hook('choice_reactors')
def choice_owners(engine: Any) -> tuple[str, ...]:
    """Printed personal choices stay human-owned on another actor's AI turn.

    The general service filters these actual feature owners by controller mode;
    automatic actors still decide from their own information. No Jigoku row
    means no added chooser and no changed legacy reaction policy.
    """
    return tuple(aid for aid,rows in getattr(engine,'typed_passive_rows',{}).items()
                 if any(r.get('block')=='path_rider' and r.get('kind')=='jigoku' for r in rows))
