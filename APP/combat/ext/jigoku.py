"""Jigoku Subpath riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Jigoku (the five features and their Normalized Procedures). Owned rows:
``{"type": "path_passive", "kind": "jigoku", "role": "eat_the_flame" | "pain_eater" | "hellwalker"}``; Burning Brand is a paid
unarmed-hit rider whose option runs ``burning_brand``; Asura's Rage is the named state "asura_s_rage".

Eat the Flame      (Hell-Tempered) after typed hostile Fire damage takes at least 1 Hit Point: the Reaction and 1 Stamina
                   (asked) for Temporary Hit Points equal to the Fire damage taken, at most twice Proficiency Bonus. Not after
                   Asura's Rage has ended this fight (the cooling rite comes after the scene).
Pain Eater         once per round after a hostile creature's typed damage reaches you: mark it (asked) until the end of your
                   next turn -- one mark of yours at a time; your first unarmed hit on it adds Proficiency Bonus damage (the
                   strike's type), ends the mark and asks one: Temporary HP PB, move 5 feet without provoking, Advantage on
                   your next save before your next turn, or it cannot take Reactions until the start of its next turn.
Burning Brand      (Flame Fist) after an unarmed hit, 1 Stamina, once per turn: Constitution save; failure, Burning (the
                   table's Burning condition, so Extinguish flames ends it): 1d8 Fire at the start of each of its turns (2d8
                   at CL17+), the save repeated at the end of each of its turns; success, 1d8 Fire now. One brand per
                   source, refreshed. Your unarmed strikes may deal Fire damage (path_riders unarmed_types add).
Hellwalker         Advantage on saves against Frightened (save_advantage row); at the start of your turn inside or next to an
                   active fire, smoke, magma or ash area (a zone whose name or terrain says so), one choice (asked): move 10
                   feet without provoking, Advantage on your next unarmed attack this turn, Temporary HP PB, or ignore
                   Difficult Terrain this turn.
Asura's Rage       state "asura_s_rage" (1 minute): Advantage on unarmed attack rolls, Resistance to all but Force, Radiant and
                   Void (typed), Frightened immunity, unarmed strikes may deal Fire or Necrotic, once per turn + 3d6 Fire or
                   Necrotic on an unarmed hit; once per round after a hostile creature's typed damage, move up to 10 feet
                   without provoking (asked), and once per round, if it is within reach, your Reaction for an unarmed strike
                   against it (asked). When it ends: 1 Exhaustion level, and Eat the Flame is gone for this fight.
Every hook returns early for a creature without these rows or states.
"""

from __future__ import annotations

from ..paid_relocation import activation

import re
from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.jigoku.feature."
RAGE = "asura_s_rage"
MARK = "condition:typed.pain_eater_mark"
COOLED = "condition:typed.eat_the_flame_spent"
NEXT_UNARMED = "condition:typed.hellwalker_unarmed_advantage"
NO_DIFFICULT = "condition:typed.hellwalker_ignores_difficult"
HELLISH = re.compile(r"fire|flame|smoke|magma|lava|ash|ember|burn|inferno|blaze", re.I)


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
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _unarmed(ctx: Any) -> bool:
    return ".natural." in ctx.source or any(isinstance(e, dict) and e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                                            for e in ctx.typed.get("effects") or [])


def _context(engine: Any, owner: Any, target: Any, intent: Any, feature: str, name: str) -> Any:
    from .. import typed_executor as te
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    action = ActionDefinition(source_definition_id=PREFIX + feature, display_name=name, owner_id=owner.entity_id, economy=EconomyKind.NONE,
                              resolution_kind="TYPED", target_kind="HOSTILE_ENTITY")
    row = next((r for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(owner.entity_id, []) if r.get("block") == "path_rider"), {})
    numbers = {"pb": _pb(owner), "cl": int(row.get("cl") or 1), "save_dc": int(row.get("save_dc") or 10)}
    return te.Context(engine, owner, action, intent, {"effects": [], "numbers": numbers, "duration": {"kind": "instant"}, "riders": []},
                      [target], target, {})


def _move(ctx: Any, mover: Any, feet: int, choice_id: str, name: str) -> None:
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    paths = routes(ctx.engine, mover, feet)
    if not paths:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "jigoku_move", mover.entity_id), mover, choice_id, sorted(paths),
                 allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=mover.entity_id,
                 prompt=f"{name}: {mover.display_name} may move up to {feet} feet without provoking Opportunity Attacks.")
    if picked and picked[0] in paths:
        step(ctx.engine, mover, paths[picked[0]], PREFIX + "jigoku")




# ------------------------------------------------------------------------------------ after hostile typed damage
@hook("damage_dealt")
def after_hostile_damage(ctx: Any, target: Any, amount: int) -> None:
    engine, other = ctx.engine, ctx.actor
    if target is None or other is None or target is other or other.team_id == target.team_id or not target.active or amount <= 0:
        return
    roles = _roles(engine, target)
    raging = _raging(engine, target)
    if not roles and not raging:
        return
    if "eat_the_flame" in roles:
        _eat_the_flame(ctx, target)
    if "pain_eater" in roles and other.active:
        _pain_mark(ctx, target, other)
    if raging:
        _rage_answers(ctx, target, other)


def _eat_the_flame(ctx: Any, owner: Any) -> None:
    engine = ctx.engine
    # Fire packets of this same hit: an attached rider's Fire can land before the primary packet.
    taken = sum(int(packet.get("hp_damage") or 0) for packet in ctx.damage_packets
                if str(packet.get("damage_type") or "").upper() == "FIRE")
    if taken < 1 or not owner.reaction_available:
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
        typed_reactions._open(engine, {"feature_id": PREFIX + "hell_tempered"}, owner, (ctx.actor.entity_id,), "DAMAGE_COMMITTED")
        owner.reaction_available = False
        owner.turn_flags["_round_eat_the_flame"] = int(engine.state.round_number)
        engine._spend_resource(owner, "resource:core.stamina", 1, PREFIX + "hell_tempered")
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
                            data={"label": f"Pain Eater: marked by {owner.display_name}"})


def _rage_answers(ctx: Any, owner: Any, other: Any) -> None:
    engine = ctx.engine
    round_no = int(engine.state.round_number)
    if owner.turn_flags.get("_round_asura_move") != round_no:
        with activation(engine, owner, PREFIX + RAGE):
            owner.turn_flags["_round_asura_move"] = round_no
            sub = _context(engine, owner, owner, ctx.intent, RAGE, "Asura's Rage")
            _move(sub, owner, 10, "choice:needle.asura_move", "Asura's Rage")
    if owner.turn_flags.get("_round_asura_strike") == round_no or not owner.reaction_available or not other.active:
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
        typed_reactions._open(engine, {"feature_id": PREFIX + RAGE}, owner, (other.entity_id,), "DAMAGE_COMMITTED")
        owner.reaction_available = False
        strike = {"type": "attack", "attack_kind": "unarmed", "count": 1}
        te.run_effects(typed_reactions.triggered_context(engine, owner, other, {"feature_id": PREFIX + RAGE, "name": "Asura's Rage", "effects": [strike],
                                                                               "numbers": {"pb": _pb(owner)}}, ctx.intent), [strike])


# ------------------------------------------------------------------------------------------ unarmed hits
@hook("after_hit")
def jigoku_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if kind != "unarmed" or target is None or not target.active or target.team_id == actor.team_id:
        return
    from .. import typed_executor as te

    if _raging(engine, actor) and actor.turn_flags.get("_round_asura_hit") != _stamp(engine):
        actor.turn_flags["_round_asura_hit"] = _stamp(engine)
        te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}),
                       [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 3, "sides": 6}, "damage_types": ["fire", "necrotic"],
                         "evidence": "Asura's Rage: once per turn + 3d6 Fire or Necrotic"}])
    held = next((c for c in target.conditions.values() if c.condition_id == MARK and c.source_actor_id == actor.entity_id), None)
    if held is None or not target.active:
        return
    target.conditions.pop(held.instance_id)
    engine._append_event("CONDITION_REMOVED", PREFIX + "pain_eater", actor_id=actor.entity_id, target_ids=(target.entity_id,),
                         payload={"condition_id": MARK, "instance_id": held.instance_id, "reason": "CONSUMED"})
    weapon = ctx.typed.get("weapon") or {}
    kinds = [str(k).lower() for k in (weapon.get("damage_types") or [weapon.get("damage_type") or "bludgeoning"])]
    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={})
    te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "flat": _pb(actor), "damage_types": kinds, "evidence": "Pain Eater"}])
    from .needle import ask, checkpoint_id

    labels = {"temp_hp": f"Gain {_pb(actor)} Temporary Hit Points", "move": "Move 5 feet without provoking",
              "save": "Advantage on your next saving throw before your next turn", "no_reactions": f"{target.display_name} cannot take Reactions until its next turn"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "pain_eater_hit", target.entity_id), actor, "choice:needle.pain_eater_benefit", list(labels),
                 labels=labels, target_id=target.entity_id, name="Pain Eater", prompt=f"Pain Eater: your marked foe {target.display_name} is hit. Choose one.")
    choice = picked[0] if picked else "temp_hp"
    if choice == "temp_hp":
        te.run_effects(sub, [{"type": "temp_hp", "applies_to": "self", "formula": "pb"}])
    elif choice == "move":
        _move(sub, actor, 5, "choice:needle.pain_eater_move", "Pain Eater")
    elif choice == "save":
        te.run_effects(sub, [{"type": "advantage", "applies_to": "self", "on": "your next saving throw", "expires_on": "START_OF_SELF_NEXT_TURN"}])
    elif target.active:
        te.run_effects(sub, [{"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}])


@effect("burning_brand")
def burning_brand(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te

    target = ctx.target
    if target is None or not target.active:
        return
    dice = 2 if int(ctx.numbers.get("cl") or 1) >= 17 else 1
    te.run_effects(ctx, [{"type": "save", "ability": "con", "evidence": "Burning Brand: Constitution saving throw",
                          "on_fail": [{"type": "condition", "applies_to": "target", "condition": "burning", "expires_on": "UNTIL_REMOVED",
                                       "repeat_save": {"ability": "CON", "when": "end"},
                                       "condition_data": {"burn": 0, "brand_dice": dice, "label": f"Burning Brand: {dice}d8 Fire at the start of each turn"}}],
                          "on_success": [{"type": "damage", "applies_to": "target", "dice": {"count": 1, "sides": 8}, "damage_types": ["fire"]}]}])


@hook("turn_start_choice")
def brand_burns(engine: Any, actor: Any) -> None:
    """A Burning Brand's start-of-turn packet (the table's Burn deals none: its "burn" is 0)."""
    from .. import typed_executor as te

    for held in [c for c in actor.conditions.values() if c.condition_id == "condition:typed.burning" and (c.data or {}).get("brand_dice")]:
        owner = engine.state.actors.get(held.source_actor_id)
        if owner is None or not actor.active:
            continue

        te.run_effects(_context(engine, owner, actor, getattr(engine, "_active_intent", None), "flame_fist", "Burning Brand"),
                       [{"type": "damage", "applies_to": "target", "dice": {"count": int(held.data["brand_dice"]), "sides": 8}, "damage_types": ["fire"],
                         "evidence": "Burning Brand"}])


# ------------------------------------------------------------------------------------------------- Hellwalker
def _hellish_cells(engine: Any, actor: Any) -> bool:
    from .. import zones

    near = {(actor.position.x + dx, actor.position.y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    for cell in engine._footprint_cells(actor) if hasattr(engine, "_footprint_cells") else ():
        near |= {(cell.x + dx, cell.y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    for zone in zones.typed_zones(engine):
        profile = zone.trigger_profile or {}
        words = " ".join([str(profile.get("name") or ""), " ".join(str(t) for t in profile.get("terrain") or []), zone.source_definition_id])
        if zone.active and HELLISH.search(words) and any((c.x, c.y) in near for c in zone.affected_cells):
            return True
    return False


@hook("turn_start_choice")
def hellwalker(engine: Any, actor: Any) -> None:
    if "hellwalker" not in _roles(engine, actor) or not actor.active or not _hellish_cells(engine, actor):
        return
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
                                data={"label": labels[choice]})


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
    return list(dict.fromkeys([*(str(k).upper() for k in kinds or []), "FIRE", "NECROTIC"]))


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
        forged_exhaustion.add(engine, holder, 1, PREFIX + RAGE)
        if not any(c.condition_id == COOLED for c in holder.conditions.values()):
            engine._apply_condition(holder, COOLED, PREFIX + RAGE, holder.entity_id, expires_on="UNTIL_REMOVED",
                data={"label": "Eat the Flame is unavailable until a cooling rite after the scene"})
        if not any(c.condition_id == SIGNAL and c.source_definition_id == PREFIX + RAGE for c in holder.conditions.values()):
            engine._apply_condition(holder, SIGNAL, PREFIX + RAGE, holder.entity_id, expires_on="UNTIL_REMOVED",
                data={"label": "Hell-Signaled", "audience": ["infernal", "daemonic"]})
        note(engine, PREFIX + RAGE, holder, f"Asura's Rage ends: {holder.display_name} gains 1 Exhaustion level and is Hell-Signaled.")
