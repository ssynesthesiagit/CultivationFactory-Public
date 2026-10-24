"""Heaven-Devouring Maw Body (rider lane C7, 2026-09-30: "i want everything we can automated").

Devoured Essence here records one damage type per Essence (printed record: "Each Essence records one valid damage type";
maximum Proficiency Bonus, +3 during Devour Heaven and Earth; valid: Acid, Cold, Fire, Force, Lightning, Necrotic, Poison,
Psychic, Radiant, Thunder). The pool is the shared named resource ``resource:named.devoured_essence``; the types sit beside it
in ``condition:typed.devoured_types`` (a list of strings, oldest first). Owned rows: ``path_passive`` kind ``devouring_maw``
with ``role`` swallow / feast / regurgitate / technique / devour.

Swallow Hostile Power  its Reaction row only answers damage of a valid type (row_allowed); 2d8 + CON (4d10 + CON during Devour
                       Heaven and Earth: reaction_amount); if it prevented at least 1 point, 1 Essence of that type once the
                       packet has resolved (one normal gain a round, up to the maximum). Maw Strike: once per turn after an
                       unarmed hit, spend 1 Essence (asked; its type) for +2d8/3d8/4d8 (by CL; 6d8 during Devour) of that type.
Feast upon Protection  once per turn after an unarmed hit, spend 3 Essence (asked): Constitution save; failure: one temporary
                       protection of the target (Temporary HP, a temporary AC bonus, Resistance or damage reduction from a
                       lasting effect of source CL at most 2 above yours) is set aside until the start of your next turn, and
                       +4d8 of a spent type; success: +2d8.
Regurgitate Calamity   ``maw_regurgitate`` {"mode": "creature" | "line"}: 1 to 3 Essence of one type (asked); a ranged
                       Cultivation Attack for 3d8 per Essence, or a Dexterity save for 2d8 per Essence (half on a success).
Swallow the Technique  its Reaction row answers valid-type damage that is not a melee attack; 4d10 + CON; if it prevented all of
                       it, 2 Essence of that type after the packet.
Devour Heaven and Earth  named state "devour_heaven_and_earth": the numbers above, supernatural Bludgeoning/Piercing/Slashing
                       become valid, once per round 1 Essence when a hostile creature within 60 feet spends CP (the type its
                       activation dealt, else Force), and the World-Eating Bite (once per turn after an unarmed hit, 5 Essence,
                       asked: +10d8 of a consumed type, Constitution save; failure ends one temporary lasting effect helping the
                       target, or strips its Temporary HP; either way it cannot gain Temporary HP until the start of your next turn).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.heaven_devouring_maw_body.feature."
ESSENCE = "resource:named.devoured_essence"
TYPES_RECORD = "condition:typed.devoured_types"
SET_ASIDE = "condition:typed.feast_set_aside"
VALID = ("ACID", "COLD", "FIRE", "FORCE", "LIGHTNING", "NECROTIC", "POISON", "PSYCHIC", "RADIANT", "THUNDER")
PHYSICAL = ("BLUDGEONING", "PIERCING", "SLASHING")
DEVOUR = "devour_heaven_and_earth"


def _roles(engine: Any, actor: Any) -> dict[str, dict[str, Any]]:
    return {str(row.get("role")): row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "path_rider" and row.get("kind") == "devouring_maw"}


def _devour(engine: Any, actor: Any) -> bool:
    from .states import active

    return bool(active(engine, actor, DEVOUR))


def stored(actor: Any) -> list[str]:
    held = next((c for c in actor.conditions.values() if c.condition_id == TYPES_RECORD), None)
    types = list((held.data or {}).get("types") or []) if held is not None else []
    return types[: int(actor.resources.get(ESSENCE, 0) or 0)]


def _write(engine: Any, actor: Any, types: list[str], source: str) -> None:
    held = next((c for c in actor.conditions.values() if c.condition_id == TYPES_RECORD), None)
    if held is not None:
        actor.conditions.pop(held.instance_id)
        engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": TYPES_RECORD, "instance_id": held.instance_id})
    engine._apply_condition(actor, TYPES_RECORD, source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"types": list(types), "label": "Devoured Essence: " + (", ".join(t.title() for t in types) or "none")})


def _maximum(engine: Any, actor: Any) -> int:
    pb = int(next(iter(_roles(engine, actor).values()), {}).get("pb") or actor.proficiency_bonus or 2)
    return pb + (3 if _devour(engine, actor) else 0)


def gain(engine: Any, actor: Any, kind: str, source: str, *, normal: bool = True, count: int = 1) -> int:
    """Gain Essence of ``kind`` up to the Maw's maximum; a normal gain is once per round. Returns how many were stored."""
    if ESSENCE not in actor.resources:
        return 0
    if normal and actor.turn_flags.get("_round_essence_gain") == int(engine.state.round_number):
        return 0
    types = stored(actor)
    room = max(0, _maximum(engine, actor) - len(types))
    count = min(count, room)
    if count <= 0:
        return 0
    engine._gain_resource(actor, ESSENCE, count, source)
    _write(engine, actor, types + [kind.upper()] * count, source)
    if normal:
        actor.turn_flags["_round_essence_gain"] = int(engine.state.round_number)
    return count


def spend(engine: Any, actor: Any, kinds: list[str], source: str) -> None:
    types = stored(actor)
    for kind in kinds:
        types.remove(kind)
    engine._spend_resource(actor, ESSENCE, len(kinds), source)
    _write(engine, actor, types, source)


def _valid(engine: Any, actor: Any, kind: str) -> bool:
    """A valid stored type; during Devour Heaven and Earth also Bludgeoning/Piercing/Slashing from a supernatural source (a
    technique, or a weapon that is not mundane) -- read from the packet now being dealt."""
    kind = str(kind or "").upper()
    if kind in VALID:
        return True
    if kind not in PHYSICAL or not _devour(engine, actor):
        return False
    packet = getattr(engine, "_typed_damage_packet", None) or {}
    action = engine.action_catalog.get(str(packet.get("source") or ""))
    typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
    return not (typed.get("weapon") and typed.get("mundane", True))


def _pick_type(engine: Any, actor: Any, intent: Any, prompt: str, count: int = 1, target_id: str | None = None) -> list[str] | None:
    """Ask which stored types to spend (``count`` Essence, any mix); None when the owner declines."""
    from .needle import ask, checkpoint_id

    types = stored(actor)
    if len(types) < count:
        return None
    options = sorted(set(types))
    if count == 1:
        picked = ask(engine, intent, checkpoint_id(engine, "maw_type", actor.entity_id), actor, "choice:needle.maw_type", options,
                     allow_decline=True, labels={o: f"Spend 1 {o.title()} Essence" for o in options}, prompt=prompt, target_id=target_id)
        return [picked[0]] if picked else None
    picked = ask(engine, intent, checkpoint_id(engine, "maw_types", actor.entity_id), actor, "choice:needle.maw_types", ["spend"],
                 allow_decline=True, labels={"spend": f"Spend {count} Essence (" + ", ".join(t.title() for t in types[:count]) + ")"},
                 prompt=prompt, target_id=target_id)
    return types[:count] if picked else None


# ------------------------------------------------------------------------------------------- Swallow Hostile Power
@hook("row_allowed")
def maw_reactions(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    feature = str(row.get("feature_id") or "")
    if feature not in (PREFIX + "swallow_hostile_power", PREFIX + "swallow_the_technique"):
        return None
    kind = str(getattr(engine, "_typed_pending_damage_type", None) or "").upper()
    packet = getattr(engine, "_typed_damage_packet", None) or {}
    if not _valid(engine, actor, kind):
        return False
    if feature.endswith("swallow_the_technique") and packet and not packet.get("ranged"):
        return False  # "Cannot consume a melee attack"
    return None


@hook("reaction_amount")
def devour_swallow(engine: Any, actor: Any, row: dict[str, Any], eff: dict[str, Any]) -> int | None:
    if str(row.get("feature_id") or "") != PREFIX + "swallow_hostile_power" or not _devour(engine, actor):
        return None
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=4, sides=10, modifier=int((row.get("numbers") or {}).get("key_mod") or 0)),
                              actor_id=actor.entity_id, reason=f"REACTION:{row.get('feature_id')}", critical=False)
    engine._record_roll(roll)
    return int(roll.total)


@hook("event")
def essence_after_swallow(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    last = engine.events[-1] if engine.events else None
    if event_type == "REACTION_RESOLVED" and last is not None and last.source_definition_id in (PREFIX + "swallow_hostile_power", PREFIX + "swallow_the_technique"):
        payload = kwargs.get("payload") or {}
        before, after = int(payload.get("pending_before") or 0), int(payload.get("pending_after") or 0)
        kind = str(getattr(engine, "_typed_pending_damage_type", None) or "FORCE").upper()
        technique = last.source_definition_id.endswith("swallow_the_technique")
        if (technique and after == 0 and before > 0) or (not technique and before > after):
            engine.__dict__.setdefault("_maw_pending", []).append((kwargs.get("actor_id"), kind, 2 if technique else 1, not technique))
    elif event_type == "DAMAGE_COMMITTED":
        waiting = engine.__dict__.get("_maw_pending") or []
        if not waiting:
            return
        engine.__dict__["_maw_pending"] = []
        for actor_id, kind, count, normal in waiting:
            actor = engine.state.actors.get(actor_id or "")
            if actor is not None and actor.active:
                gain(engine, actor, kind if kind in VALID or kind in PHYSICAL else "FORCE", PREFIX + "swallow_hostile_power", normal=normal, count=count)


# ------------------------------------------------------------------------------------------ on-hit spends
def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


@hook("after_hit")
def maw_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    roles = _roles(engine, actor)
    if kind != "unarmed" or target is None or not target.active or not roles or not stored(actor):
        return
    from .. import typed_executor as te

    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={})
    devour = _devour(engine, actor)
    if devour and actor.turn_flags.get("_round_world_bite") != _stamp(engine) and len(stored(actor)) >= 5:
        kinds = _pick_type(engine, actor, ctx.intent, f"World-Eating Bite: {ctx.action.display_name} hit {target.display_name}; spend 5 Essence "
                           "for +10d8 and a Constitution save?", count=5, target_id=target.entity_id)
        if kinds:
            actor.turn_flags["_round_world_bite"] = _stamp(engine)
            spend(engine, actor, kinds, PREFIX + "devour_heaven_and_earth")
            te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 10, "sides": 8}, "damage_types": [kinds[0].lower()]},
                                 {"type": "save", "ability": "con", "on_fail": [{"type": "maw_break_defense"}], "on_success": []},
                                 {"type": "deny_temp_hp", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN"}])
    if "feast" in roles and target.active and actor.turn_flags.get("_round_feast") != _stamp(engine) and len(stored(actor)) >= 3:
        kinds = _pick_type(engine, actor, ctx.intent, f"Feast upon Protection: {ctx.action.display_name} hit {target.display_name}; spend 3 Essence?",
                           count=3, target_id=target.entity_id)
        if kinds:
            actor.turn_flags["_round_feast"] = _stamp(engine)
            spend(engine, actor, kinds, PREFIX + "feast_upon_protection")
            dtype = kinds[0].lower()
            te.run_effects(sub, [{"type": "save", "ability": "con", "evidence": "Feast upon Protection: Constitution saving throw",
                                  "on_fail": [{"type": "maw_set_aside"}, {"type": "damage", "applies_to": "target", "dice": {"count": 4, "sides": 8}, "damage_types": [dtype]}],
                                  "on_success": [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": [dtype]}]}])
    if "swallow" in roles and target.active and actor.turn_flags.get("_round_maw_strike") != _stamp(engine) and stored(actor):
        kinds = _pick_type(engine, actor, ctx.intent, f"Maw Strike: {ctx.action.display_name} hit {target.display_name}; spend 1 Essence for extra damage of its type?",
                           target_id=target.entity_id)
        if kinds:
            actor.turn_flags["_round_maw_strike"] = _stamp(engine)
            spend(engine, actor, kinds, PREFIX + "swallow_hostile_power")
            cl = int(ctx.numbers.get("cl") or 1)
            count = 6 if devour else 4 if cl >= 17 else 3 if cl >= 11 else 2
            te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": count, "sides": 8}, "damage_types": [kinds[0].lower()],
                                  "evidence": "Maw Strike"}])


def _protections(ctx: Any, target: Any) -> dict[str, tuple[str, str, Any]]:
    from . import end_effect

    out: dict[str, tuple[str, str, Any]] = {}
    if int(target.temporary_hp or 0) > 0:
        out["temp_hp"] = ("temp_hp", "", int(target.temporary_hp))
    cl = int(ctx.numbers.get("cl") or 1)
    for kind, key, item in end_effect.found(ctx.engine, target, {"select": "beneficial"}):
        if end_effect.source_cl(ctx, item) > cl + 2:
            continue
        if kind == "modifier" and item.target_field in ("armor_class", "armor_class_vs_melee", "armor_class_vs_ranged", "damage_resistance", "damage_reduction"):
            label = f"{item.target_field.replace('_', ' ')} {item.value}".strip()
            out[f"modifier:{key}"] = (kind, key, label)
    return out


@effect("maw_set_aside")
def set_aside(ctx: Any, row: dict[str, Any]) -> None:
    """Feast upon Protection: one protection is inactive until the start of the owner's next turn (restored then)."""
    from .needle import ask, checkpoint_id

    target = ctx.target
    if target is None or not target.active:
        return
    options = _protections(ctx, target)
    if not options:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "feast_protection", target.entity_id), ctx.actor, "choice:needle.feast_protection",
                 list(options), labels={k: ("Temporary Hit Points" if k == "temp_hp" else str(v[2]).title()) for k, v in options.items()},
                 prompt=f"Feast upon Protection: choose the protection {target.display_name} loses until the start of your next turn.",
                 target_id=target.entity_id)
    if not picked:
        return
    kind, key, value = options[picked[0]]
    if kind == "temp_hp":
        before = int(target.temporary_hp)
        target.temporary_hp = 0
        ctx.engine._append_event("TEMP_HP_GRANTED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(target.entity_id,),
                                 payload={"offered": 0, "before": before, "after": 0, "removed_by": "Feast upon Protection"})
        record = {"temp_hp": before}
    else:
        modifier = target.modifiers.pop(key)
        ctx.engine._append_event("MODIFIER_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(target.entity_id,),
                                 payload={"modifier_id": key, "reason": "FEAST_UPON_PROTECTION"})
        record = {"modifier": {"source": modifier.source_definition_id, "field": modifier.target_field, "operation": modifier.operation,
                               "value": modifier.value, "scope": modifier.scope, "expires_on": modifier.expires_on}}
    ctx.engine._apply_condition(target, SET_ASIDE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "A protection set aside by Feast upon Protection", **record})


@hook("turn_start")
def restore_protections(engine: Any, actor: Any) -> None:
    for holder in engine.state.actors.values():
        for held in [c for c in holder.conditions.values() if c.condition_id == SET_ASIDE and c.source_actor_id == actor.entity_id]:
            holder.conditions.pop(held.instance_id)
            engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=actor.entity_id, target_ids=(holder.entity_id,),
                                 payload={"condition_id": SET_ASIDE, "instance_id": held.instance_id})
            data = held.data or {}
            if data.get("temp_hp") and holder.active:
                engine._grant_temp_hp(holder, int(data["temp_hp"]), held.source_definition_id, actor.entity_id)
            elif data.get("modifier") and holder.active:
                row = data["modifier"]
                engine._add_modifier(holder, row["source"], row["field"], row["operation"], row["value"], row["scope"], expires_on=row["expires_on"])


@effect("maw_break_defense")
def break_defense(ctx: Any, row: dict[str, Any]) -> None:
    """World-Eating Bite, failed save: end one temporary lasting effect helping the target; with none, strip its Temporary HP."""
    from . import end_effect
    from .needle import ask, checkpoint_id

    target = ctx.target
    if target is None or not target.active:
        return
    found = [(kind, key, item) for kind, key, item in end_effect.found(ctx.engine, target, {"select": "beneficial"})
             if end_effect.source_cl(ctx, item) <= int(ctx.numbers.get("cl") or 1)]
    if not found:
        if int(target.temporary_hp or 0) > 0:
            before = int(target.temporary_hp)
            target.temporary_hp = 0
            ctx.engine._append_event("TEMP_HP_GRANTED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(target.entity_id,),
                                     payload={"offered": 0, "before": before, "after": 0, "removed_by": "World-Eating Bite"})
        return
    ids = [f"{kind}:{key}" for kind, key, _item in found]
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "world_bite", target.entity_id), ctx.actor, "choice:needle.world_bite", ids,
                 target_id=target.entity_id, prompt=f"World-Eating Bite: choose the temporary effect helping {target.display_name} that ends.")
    for kind, key, item in found:
        if picked and f"{kind}:{key}" == picked[0]:
            end_effect.remove_instance(ctx, target, kind, key, item)


# ------------------------------------------------------------------------------------------ Regurgitate Calamity
@effect("maw_regurgitate")
def regurgitate(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    types = stored(actor)
    if not types:
        return
    options = [f"{kind}:{n}" for kind in sorted(set(types)) for n in range(min(3, types.count(kind)), 0, -1)]
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "regurgitate", actor.entity_id), actor, "choice:needle.regurgitate", options,
                 labels={o: f"{o.split(':')[1]} {o.split(':')[0].title()} Essence" for o in options},
                 prompt=f"Regurgitate Calamity: choose the Essence {actor.display_name} spends (one type, up to 3).", target_id=actor.entity_id)
    if not picked:
        return
    kind, count = picked[0].split(":")[0], int(picked[0].split(":")[1])
    spend(engine, actor, [kind] * count, ctx.source)
    dtype = kind.lower()
    if row.get("mode") == "line":
        te.run_effects(ctx, [{"type": "save", "ability": "dex", "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 2 * count, "sides": 8}, "damage_types": [dtype]}],
                              "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": [dtype]}]}])
    else:
        te.run_effects(ctx, [{"type": "attack", "attack_kind": "cultivation_ranged", "count": 1,
                              "on_hit": [{"type": "damage", "applies_to": "target", "dice": {"count": 3 * count, "sides": 8}, "damage_types": [dtype]}], "on_miss": []}])


@hook("candidate_allowed")
def regurgitate_needs_essence(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    if not any(isinstance(e, dict) and e.get("type") == "maw_regurgitate" for e in typed.get("effects") or []):
        return None
    return None if stored(actor) else False


# ---------------------------------------------------------------------------------------- Devour Heaven and Earth
@hook("technique_used")
def devour_cp(ctx: Any) -> None:
    """Once per round when a hostile creature within 60 feet spends CP, 1 Essence after its feature resolves."""
    if int(ctx.numbers.get("_cp_cost") or 0) <= 0:
        return
    engine, user = ctx.engine, ctx.actor
    for owner in engine.state.actors.values():
        if not owner.active or owner.team_id == user.team_id or not _devour(engine, owner) or engine._distance_actor_to_actor(owner, user) > 60:
            continue
        if owner.turn_flags.get("_round_devour_cp") == int(engine.state.round_number):
            continue
        dealt = next((str((e.payload or {}).get("damage_type") or "").upper() for e in reversed(engine.events[-40:])
                      if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == ctx.source), "")
        if gain(engine, owner, dealt if dealt in VALID else "FORCE", PREFIX + "devour_heaven_and_earth", normal=False):
            owner.turn_flags["_round_devour_cp"] = int(engine.state.round_number)
            note(engine, PREFIX + "devour_heaven_and_earth", owner, f"Devour Heaven and Earth: {owner.display_name} devours 1 Essence from {user.display_name}'s technique.")
