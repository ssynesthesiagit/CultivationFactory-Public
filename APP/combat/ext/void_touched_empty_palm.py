"""Empty Palm (CL6) -- tianxia.subpath.qi.void_touched_cultivator.feature.empty_palm.

One action, one hit, then one of the three printed operations. Ownership is the
foundation's: the compiled action must carry the family source and the permanent
Void Scar recorded at acquisition (combat/ext/void_touched_cultivator.py), so a
character without the Secret Law gets no action at all and every hook here
returns early.

The three operations are three compiled options of the same action (the compiler
turns each printed option into its own row sharing the ability's Action economy,
touch range and 3 Qi cost), so all three are offered to humans and to AI seats
alike. The hit's shared part -- the 4d8 + key modifier Force-or-Void damage and
the Void Mark -- rides inside each option, which is why a miss neither damages
nor marks. The damage type is a real question for a player-controlled seat
(``damage_type_choice``); a computer-controlled seat keeps the engine's own
automatic choice among the printed types.

Operations (typed effect ``void_touched_empty_palm``, one row per operation):

Unravel Manifestation suppresses ONE real active effect. Eligible: the typed
conditions and modifiers a technique left on the target (a Path or Subpath
transformation, a Sphere talent's state, a Recorded Art, a Forged Technique, a
Domain Armament manifestation, a talisman, seal, ward or possession tether, a
curse with a supernatural structure -- every one of them is stored as a typed
condition or modifier), the stored areas whose squares cover the target or the
user (Qi fields, temporary barriers, Formation arrays, wards), and a summoned
Cultivation Asset within the user's touch. A ``mark.``/``suppressed.``
bookkeeping row is not an effect and is never offered. The comparison reads the
effect's own Source CL (the shared reader in combat/ext/end_effect.py) against
the user's CL:

  * lower Source CL and not a Secret/Immortal/artifact or explicitly absolute
    effect: suppressed until the start of the user's next turn, with no check;
  * equal Source CL: a Cultivation Check against the effect's save DC, then the
    same suppression;
  * higher Source CL: the effect's own recorded resistance (``origin_save``)
    first, then the Cultivation Check, and the suppression lasts until the end
    of the current turn.

Suppression reuses the existing contracts rather than inventing one: a creature
condition or modifier is renamed in place by ``end_effect.suppress`` (its own
duration keeps ageing, its costs are not refunded, nothing is removed), a stored
area is taken off its squares by ``area_suppression.suppress``, and a summoned
asset is made inert by a condition carrying the engine's own ``no_actions``/
``no_reactions``/``speed_zero`` rules. Nothing here destroys an item, a
Foundation, a Method, a Golden Core, a Nascent Soul or a complete Path: every
branch only hides an effect for a stated time.

The sole-Anchor clause is the one cascade this table can read: when the chosen
condition is the only live instance of its own source on the target and a stored
area is anchored to that target from that same source
(``trigger_profile.anchor_id``), the area is suppressed with it.

Empty the Meridian rolls the printed Constitution save against the user's real
save DC. On a failure the creature loses the chosen current Cultivation Point
pool (Qi, Stamina or Resonance) equal to the user's Proficiency Bonus and cannot
regain Cultivation Points until the start of its next turn -- the engine's own
``condition:typed.no_cp_regain`` gate, which the engine removes at that boundary.
On a success it loses 1 point if it has any. A creature with no Cultivation
Points in any pool instead takes 2 x Proficiency Bonus additional Force damage
beside the hit's damage. The printed text does not say who picks the pool, so
the losing creature's controller picks it: a player is asked, and a computer-
controlled creature takes its largest pool.

Hollow the Weapon asks the target's controller which item it wields, carries or
controls -- each usable weapon, a carried Shield, and a live Domain Armament --
then rolls the printed Charisma save. A failed save suppresses every cultivated
property of that item until the start of the user's next turn: a weapon's or
Domain Armament's own attack action is disabled through the engine's existing
``disables_action`` condition data, a Shield's Shield Bonus is taken back
through the ``ac`` hook, and a floating Domain Armament is made inert in its
space (its own condition is suppressed, so its owner can no longer use it). A
successful save suppresses exactly one named property until the end of the
current turn. The physical item stays where it is: nothing is destroyed,
duplicated, moved or dropped.

Hooks used (both documented in combat/ext/__init__.py):
  damage_type_choice   the printed Force-or-Void choice, asked of a player seat
  ac                   a hollowed Shield's Shield Bonus stops applying

No engine or core file changes for this record; the shared suppression helpers
are used exactly as they document themselves.
"""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from . import effect, hook, note, run as run_hooks
from .void_touched_cultivator import PARENT, PREFIX, composed_scar, family_source

EMPTY_PALM = PREFIX + "empty_palm"
CP_POOLS = ("resource:core.qi", "resource:core.stamina", "resource:core.resonance")
POOL_NAMES = {"resource:core.qi": "Qi", "resource:core.stamina": "Stamina",
              "resource:core.resonance": "Resonance"}
NO_REGAIN = "condition:typed.no_cp_regain"
HOLLOWED_ITEM = "condition:typed.hollowed_item"
HOLLOWED_ASSET = "condition:typed.hollowed_asset"
CHOICE = "choice:needle."
CONDITION_PREFIX = "condition:typed."
ABILITY_SAVES = {"STR", "DEX", "CON", "INT", "WIS", "CHA"}
# Bookkeeping rows (a Void Mark, a suppression marker, a held-Concentration flag,
# an equipment grip, a menu pick) are not active effects: nothing that identifies
# an effect can select them.
_BOOKKEEPING = ("mark.", "suppressed.", "concentration_held", "menu", "setting", "hidden", "instant",
                "equipment_grip", "attack_mode", "hollowed_item", "hollowed_asset")


# ------------------------------------------------------------------------------------------------ ownership
def owned(action: Any) -> bool:
    """The exact acquired family feature, sealed with the recorded permanent Scar."""
    return family_source(action) == EMPTY_PALM and bool(composed_scar(action))


def _owns(ctx: Any) -> bool:
    return owned(ctx.action) and getattr(ctx.action, "owner_id", None) == ctx.actor.entity_id


# ------------------------------------------------------------------------------------------------ choices
def _ask(ctx: Any, chooser: Any, name: str, options: list[str], *, labels: dict[str, str],
         preferred: list[str], prompt: str) -> list[str]:
    """One answering seat: a player is asked, a computer-controlled creature decides for itself."""
    from .needle import ask, checkpoint_id

    return ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, name, chooser.entity_id, ctx.actor.entity_id),
               chooser, CHOICE + name, options, labels=labels, preferred=preferred,
               target_id=chooser.entity_id, prompt=prompt)


def _pool(ctx: Any, target: Any) -> str | None:
    """The pool the losing creature's controller picks; the largest pool when nobody is asked."""
    pools = [pool for pool in CP_POOLS if int(target.resources.get(pool) or 0) > 0]
    if not pools:
        return None
    preferred = [max(pools, key=lambda pool: (int(target.resources.get(pool) or 0), -CP_POOLS.index(pool)))]
    amount = int(ctx.numbers.get("pb") or 0)
    picked = _ask(ctx, target, "empty_palm_pool", pools,
                  labels={pool: f"{POOL_NAMES[pool]} ({int(target.resources.get(pool) or 0)} left)" for pool in pools},
                  preferred=preferred,
                  prompt=(f"Empty Palm — Empty the Meridian hit {target.display_name}. Choose which current Cultivation "
                          f"Point pool it loses from: {amount} points on a failed save, 1 on a successful one. "
                          "Empty Palm's Action already paid its 3 Qi."))
    return picked[0] if picked else preferred[0]


# ------------------------------------------------------------------------------------------------ operations
@effect("void_touched_empty_palm", harmful=True)
def palm_operation(ctx: Any, row: dict[str, Any]) -> None:
    """Resolve the chosen printed operation for each creature the hit reached."""
    from ..typed_executor import effect_subjects

    if not _owns(ctx):
        return
    operation = str(row.get("operation") or "")
    for target in effect_subjects(ctx, row, harmful=True):
        if not target.active:
            continue
        if operation == "unravel":
            unravel(ctx, target)
        elif operation == "meridian":
            empty_the_meridian(ctx, target)
        elif operation == "hollow":
            hollow_the_weapon(ctx, target)


# ------------------------------------------------------------------------------------------------ Empty the Meridian
def empty_the_meridian(ctx: Any, target: Any) -> None:
    engine, user = ctx.engine, ctx.actor
    pb = int(ctx.numbers.get("pb") or target.proficiency_bonus or 0)
    failed = bool(ctx.failed_save)
    pool = _pool(ctx, target)
    if pool is None:
        extra = 2 * pb
        note(engine, ctx.source, user,
             f"Empty Palm — Empty the Meridian: {target.display_name} has no Cultivation Points, so it takes {extra} "
             "additional Force damage instead.", (target,))
        _extra_force(ctx, target, extra)
        return
    wanted = pb if failed else 1
    took = min(wanted, int(target.resources.get(pool) or 0))
    if took:
        engine._spend_resource(target, pool, took, ctx.source)
    if failed:
        engine._apply_condition(target, NO_REGAIN, ctx.source, user.entity_id,
                                expires_on=_holder_start(target),
                                data={"label": (f"Empty Palm — Empty the Meridian: {target.display_name} cannot regain "
                                                "Cultivation Points (Qi, Stamina or Resonance) until the start of its "
                                                "next turn."), "source_cl": int(ctx.numbers.get("cl") or 1)})
        note(engine, ctx.source, user,
             f"Empty Palm — Empty the Meridian: {target.display_name} loses {took} {POOL_NAMES[pool]} and cannot regain "
             "Cultivation Points until the start of its next turn.", (target,))
    else:
        note(engine, ctx.source, user,
             f"Empty Palm — Empty the Meridian: {target.display_name} succeeds on its Constitution save and loses "
             f"{took} {POOL_NAMES[pool]}.", (target,))


def _holder_start(target: Any) -> str:
    from .effect_durations import holder_next_turn

    return holder_next_turn(target, "start")


def _extra_force(ctx: Any, target: Any, amount: int) -> None:
    from ..typed_executor import run_effects

    # The printed amount is exact (twice Proficiency Bonus), not a rolled amount,
    # so a Path's "one damage roll per activation" bonus does not add to it.
    ctx.damage_cache["_potency_used"] = True
    run_effects(replace(ctx, targets=[target], target=target),
                [{"type": "damage", "applies_to": "target", "flat": int(amount), "damage_types": ["force"],
                  "evidence": "additional Force damage equal to twice your Proficiency Bonus"}])


# ------------------------------------------------------------------------------------------------ Unravel Manifestation
def _usable_action(engine: Any, source: Any) -> Any:
    """The compiled action behind an effect, following a zone/variant suffix (the shared attribution rule)."""
    text = str(source or "")
    action = engine.action_catalog.get(text)
    if action is not None:
        return action
    key = max((key for key in engine.action_catalog
               if text.startswith(key + ":") or text.startswith(key + "#")), key=len, default="")
    return engine.action_catalog.get(key) if key else None


def _source_ref(ctx: Any, kind: str, item: Any) -> Any:
    """One shape for the shared Source-CL reader: a zone names its owner, an effect its source actor."""
    if kind == "zone":
        return SimpleNamespace(source_definition_id=item.source_definition_id, source_actor_id=item.owner_id,
                               instance_id=item.zone_id)
    if kind == "summon":
        record = item.summon or {}
        return SimpleNamespace(source_definition_id=str(record.get("source") or ""),
                               source_actor_id=str(record.get("owner") or ""), instance_id=item.entity_id)
    return item


def _source_id(kind: str, item: Any) -> str:
    if kind == "zone":
        return str(item.source_definition_id or "")
    if kind == "summon":
        return str((item.summon or {}).get("source") or "")
    return str(getattr(item, "source_definition_id", "") or "")


def source_cl(ctx: Any, kind: str, item: Any) -> int:
    """The effect's own Source CL, read by the shared contract (its technique, else its caster)."""
    from . import end_effect

    return end_effect.source_cl(ctx, _source_ref(ctx, kind, item))


def effect_dc(ctx: Any, kind: str, item: Any) -> int:
    """The effect's save DC: its area's own, its technique's, else the caster's Cultivation Save DC.

    These are the documented fallbacks the shared suppression readers apply.
    """
    from . import area_suppression, end_effect

    if kind == "zone":
        return area_suppression.save_dc(ctx.engine, item)
    if kind == "summon":
        record = item.summon or {}
        action = _usable_action(ctx.engine, record.get("source"))
        numbers = (((getattr(action, "parameters", None) or {}).get("typed") or {}).get("numbers") or {}) \
            if action is not None else {}
        if numbers.get("save_dc"):
            return int(numbers["save_dc"])
        owner = ctx.engine.state.actors.get(str(record.get("owner") or ""))
        return end_effect.cultivation_dc(ctx.engine, owner) if owner is not None else 15
    action = _usable_action(ctx.engine, getattr(item, "source_definition_id", ""))
    numbers = (((getattr(action, "parameters", None) or {}).get("typed") or {}).get("numbers") or {}) \
        if action is not None else {}
    if numbers.get("save_dc"):
        return int(numbers["save_dc"])
    source = ctx.engine.state.actors.get(str(getattr(item, "source_actor_id", "") or ""))
    return end_effect.cultivation_dc(ctx.engine, source) if source is not None else 15


def protected_effect(ctx: Any, kind: str, item: Any) -> bool:
    """A Secret, Immortal, artifact or explicitly absolute effect: the lower-CL branch may not touch it.

    The shared printed-record reader classifies a technique's own record. An
    effect the table cannot attribute fails closed here, so an unknown source is
    never silently suppressed.
    """
    from . import source_eligibility

    power = source_eligibility.printed_power(_usable_action(ctx.engine, _source_id(kind, item)))
    if power is None:
        return True
    return source_eligibility.protected_power(*power, extra_categories=("Secret", "Immortal", "absolute"))


def effects_on(ctx: Any, holder: Any) -> list[tuple[str, str, Any]]:
    """Every active effect the printed list can name, as the state the table really stores."""
    from ..typed_executor import is_active_typed_condition

    out: list[tuple[str, str, Any]] = []
    for key, condition in holder.conditions.items():
        name = str(condition.condition_id)
        if not name.startswith(CONDITION_PREFIX) or not is_active_typed_condition(condition):
            continue
        if any(part in name[len(CONDITION_PREFIX):] for part in _BOOKKEEPING):
            continue
        out.append(("condition", key, condition))
    for key, modifier in holder.modifiers.items():
        field = str(modifier.target_field)
        if field.startswith("suppressed:") or field == "attack_mode":
            continue
        out.append(("modifier", key, modifier))
    return out


def touching_areas(ctx: Any, holder: Any) -> list[Any]:
    """Stored areas whose squares cover the target's or the user's space (the user is touching them)."""
    from . import area_suppression

    found: dict[str, Any] = {}
    for cell in (holder.position, ctx.actor.position):
        for zone in area_suppression.areas_at(ctx.engine, cell):
            found[zone.zone_id] = zone
    return list(found.values())


def touching_summons(ctx: Any) -> list[Any]:
    """Summoned or projected Cultivation Assets the user is touching."""
    engine = ctx.engine
    out = []
    for actor in sorted(engine.state.actors.values(), key=lambda row: row.entity_id):
        if actor is ctx.actor or not actor.active or not actor.summon or actor.summon.get("status") != "present":
            continue
        if engine._distance_actor_to_actor(ctx.actor, actor) <= 5:
            out.append(actor)
    return out


def _label(ctx: Any, kind: str, item: Any) -> str:
    from . import ability_source, end_effect

    if kind == "zone":
        owner = ctx.engine.state.actors.get(str(item.owner_id or ""))
        name = ability_source.source_label(ctx.engine, item.source_definition_id)
        return f"{name}" + (f" ({owner.display_name}'s lasting area)" if owner is not None else
                            " (a lasting area)")
    if kind == "summon":
        return f"{item.display_name} — a summoned Cultivation Asset"
    detail = end_effect.describe(ctx.engine, kind, item)
    origin = ability_source.source_label(ctx.engine, _source_id(kind, item))
    owner = ctx.engine.state.actors.get(str(getattr(item, "source_actor_id", "") or ""))
    return f"{detail} from {origin}" + (f" ({owner.display_name})" if owner is not None else "")


def _effect_choices(ctx: Any, target: Any) -> tuple[list[tuple[str, str, Any]], dict[str, str]]:
    """The selectable effects, most recently applied first (the automatic first choice), then the areas,
    then a summoned asset."""
    effects = effects_on(ctx, target)
    conditions = [row for row in effects if row[0] == "condition"]
    modifiers = [row for row in effects if row[0] == "modifier"]
    conditions.sort(key=lambda row: int(getattr(row[2], "applied_sequence", 0) or 0), reverse=True)
    entries = conditions + list(reversed(modifiers)) \
        + [("zone", zone.zone_id, zone) for zone in touching_areas(ctx, target)] \
        + [("summon", actor.entity_id, actor) for actor in touching_summons(ctx)]
    labels: dict[str, str] = {}
    for kind, key, item in entries:
        labels[key] = f"{_label(ctx, kind, item)} (Source CL {source_cl(ctx, kind, item)})"
    totals = {label: list(labels.values()).count(label) for label in labels.values()}
    seen: dict[str, int] = {}
    for key in labels:
        label = labels[key]
        if totals[label] > 1:
            seen[label] = seen.get(label, 0) + 1
            labels[key] += f" (copy {seen[label]} of {totals[label]})"
    return entries, labels


def _choose_effect(ctx: Any, target: Any, entries: list[tuple[str, str, Any]],
                   labels: dict[str, str]) -> tuple[str, str, Any] | None:
    ordered = {row[1]: row for row in entries}
    picked = _ask(ctx, ctx.actor, "empty_palm_unravel", list(labels), labels=labels,
                  preferred=list(labels)[:1],
                  prompt=(f"Empty Palm — Unravel Manifestation: choose one active effect on {target.display_name}, or one "
                          "whose Anchor, manifestation or origin you are touching. A lower Source CL is suppressed at "
                          "once, an equal one after a Cultivation Check, and a higher one after its own resistance and "
                          "then the check. Empty Palm's 3 Qi is already paid."))
    key = picked[0] if picked else list(labels)[0]
    return ordered.get(key)


def _cultivation_check(ctx: Any, dc: int, label: str) -> bool:
    from . import floored

    engine, user = ctx.engine, ctx.actor
    bonus = int(ctx.numbers.get("pb") or 0) + int(ctx.numbers.get("key_mod") or 0) + sum(
        int(value) for value in run_hooks("check_bonus", ctx, user)
        if isinstance(value, int) and not isinstance(value, bool))
    roll = engine.roll_check(modifier=bonus, actor_id=user.entity_id, reason=f"CHECK:{ctx.source}:unravel")
    engine._record_roll(roll)
    roll = floored(engine, user, roll, dc)
    success = roll.total >= dc
    engine._append_event("CHECK_ROLLED", ctx.source, actor_id=user.entity_id, target_ids=(user.entity_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success,
                                  "skill": "Cultivation Check", "effect": label})
    return success


def _normal_resistance(ctx: Any, target: Any, kind: str, item: Any) -> bool:
    """The stronger effect's own printed resistance, where the fight recorded one."""
    if kind == "condition":
        data = dict(getattr(item, "data", None) or {})
        save = data.get("origin_save") if isinstance(data.get("origin_save"), dict) else data.get("repeat_save")
    elif kind == "modifier":
        save = getattr(item, "origin_save", None)
    else:
        save = None
    if not isinstance(save, dict):
        return False
    ability = str(save.get("ability") or "").upper()
    if ability not in ABILITY_SAVES:
        return False
    dc = int(save.get("dc") or 0) or effect_dc(ctx, kind, item)
    roll = ctx.engine._roll_save(target, ability, dc, ctx.source)
    return roll is not None and int(roll.total) >= dc


def _suppress(ctx: Any, target: Any, kind: str, key: str, item: Any, *, until: str) -> None:
    """Suppress one effect until ``until``: "start" (the user's next turn) or "end" (this turn's end)."""
    from . import area_suppression, end_effect
    from .effect_durations import token

    engine, user, source = ctx.engine, ctx.actor, ctx.source
    if kind in ("condition", "modifier"):
        end_effect.suppress(target, kind, key, item, rounds=1 if until == "start" else 0,
                            by=user, engine=engine, boundary=until)
        return
    expiry = (token("start", user.entity_id, int(user.turns_started) + 1) if until == "start"
              else token("end", user.entity_id, int(user.turns_started)))
    if kind == "zone":
        area_suppression.suppress(engine, user, item, expiry, source)
        return
    engine._apply_condition(item, HOLLOWED_ASSET, source, user.entity_id, expires_on=expiry,
                            data={"rule": {"no_actions": True, "no_reactions": True, "speed_zero": True},
                                  "label": (f"Empty Palm — Unravel Manifestation: {item.display_name}'s projected form "
                                            "is inert (no Actions, Reactions or movement) until the effect ends; it "
                                            "remains on the table.")})


def _anchor_areas(ctx: Any, target: Any, item: Any) -> list[Any]:
    """Stored areas this exact effect is the sole Anchor of (the one cascade the table can read)."""
    from .. import zones

    source_action = _source_id("condition", item)
    if not source_action:
        return []
    siblings = [condition for condition in target.conditions.values()
                if condition is not item and str(condition.source_definition_id or "") == source_action]
    if siblings:
        return []
    return [zone for zone in zones.typed_zones(ctx.engine)
            if str((zone.trigger_profile or {}).get("anchor_id") or "") == target.entity_id
            and zone.source_definition_id == source_action and zone.active]


def unravel(ctx: Any, target: Any) -> None:
    engine, user = ctx.engine, ctx.actor
    entries, labels = _effect_choices(ctx, target)
    if not entries:
        ctx.rider(f"Empty Palm — Unravel Manifestation: {target.display_name} has no active effect this table can "
                  "suppress, and none you are touching.")
        return
    chosen = _choose_effect(ctx, target, entries, labels)
    if chosen is None:
        return
    kind, key, item = chosen
    label = labels[key]
    mine = int(ctx.numbers.get("cl") or 1)
    theirs = source_cl(ctx, kind, item)
    if theirs < mine:
        if protected_effect(ctx, kind, item):
            ctx.rider(f"Empty Palm — Unravel Manifestation: {label} has a lower Source CL, but it is a Secret, Immortal, "
                      "artifact or absolute effect, so the printed automatic suppression does not apply; the GM decides.")
            return
        _apply(ctx, target, kind, key, item, until="start", label=label)
        return
    if theirs > mine and _normal_resistance(ctx, target, kind, item):
        note(engine, ctx.source, user,
             f"Empty Palm — Unravel Manifestation: {label} makes its own resistance and is not suppressed.", (target,))
        return
    if not _cultivation_check(ctx, effect_dc(ctx, kind, item), label):
        note(engine, ctx.source, user,
             f"Empty Palm — Unravel Manifestation: the Cultivation Check fails; {label} stays active.", (target,))
        return
    _apply(ctx, target, kind, key, item, until="start" if theirs == mine else "end", label=label)


def _apply(ctx: Any, target: Any, kind: str, key: str, item: Any, *, until: str, label: str) -> None:
    from ..typed_executor import is_active_typed_condition

    _suppress(ctx, target, kind, key, item, until=until)
    if kind == "condition" and is_active_typed_condition(item):
        for zone in _anchor_areas(ctx, target, item):
            _suppress(ctx, target, "zone", zone.zone_id, zone, until=until)
    wording = ("until the start of your next turn" if until == "start" else "until the end of the current turn")
    note(ctx.engine, ctx.source, ctx.actor,
         f"Empty Palm — Unravel Manifestation: {label} is suppressed {wording}. Its duration keeps running and its "
         "cost is not refunded.", (target,))


# ------------------------------------------------------------------------------------------------ Hollow the Weapon
def item_properties(ctx: Any, target: Any) -> list[dict[str, Any]]:
    """Items the target wields, carries or controls, each with the named properties it can lose."""
    from .. import armour
    from ..weapon_delivery import available_weapons
    from . import qi_path

    engine = ctx.engine
    items: list[dict[str, Any]] = []
    for source, action in sorted(available_weapons(engine, target).items()):
        typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
        weapon = typed.get("weapon") or {}
        if not weapon.get("implement_id"):
            continue  # an unarmed strike or an improvised weapon is not a carried item
        name = str(action.display_name).removesuffix(" attack") or str(weapon.get("implement_id"))
        items.append({"key": source, "name": name, "kind": "weapon",
                      "properties": [{"key": "attack", "action": source,
                                      "name": f"{name} attack (its cultivated weapon properties)"}]})
    shield = armour.shield_item_key(engine, target)
    if shield is not None and armour.shield_bonus_earning(engine, target):
        items.append({"key": f"shield:{shield}", "name": "Shield", "kind": "shield",
                      "properties": [{"key": "shield_bonus", "shield": shield,
                                      "name": "Shield Bonus (+2 AC from the carried Shield)"}]})
    armed = qi_path.armament_condition(target)
    if armed is not None:
        attacks = [action_id for action_id in target.action_ids
                   if engine.action_catalog.get(action_id) is not None
                   and ((engine.action_catalog[action_id].parameters or {}).get("armament") == "attack")]
        properties = [{"key": f"action:{action_id}", "action": action_id,
                       "name": "Domain Armament attack"} for action_id in attacks]
        properties.append({"key": "manifestation", "instance_id": armed.instance_id,
                           "name": "floating Domain Armament manifestation"})
        items.append({"key": "armament", "name": "Domain Armament", "kind": "armament", "properties": properties})
    return items


def hollow_the_weapon(ctx: Any, target: Any) -> None:
    engine, user = ctx.engine, ctx.actor
    items = item_properties(ctx, target)
    if not items:
        ctx.rider(f"Empty Palm — Hollow the Weapon: {target.display_name} wields, carries or controls no weapon, Shield "
                  "or Domain Armament whose cultivated properties this table can suppress.")
        return
    failed = bool(ctx.failed_save)
    by_key = {item["key"]: item for item in items}
    picked = _ask(ctx, target, "empty_palm_item", list(by_key),
                  labels={key: by_key[key]["name"] for key in by_key}, preferred=list(by_key)[:1],
                  prompt=(f"Empty Palm — Hollow the Weapon: choose one weapon, Shield or Domain Armament that "
                          f"{target.display_name} is wielding, carrying or actively controlling. The item stays where it "
                          "is; its cultivated properties stop working for the printed time."))
    item = by_key[picked[0]] if picked else items[0]
    if failed:
        for prop in item["properties"]:
            _hollow_property(ctx, target, item, prop, until="start")
        note(engine, ctx.source, user,
             f"Empty Palm — Hollow the Weapon: {target.display_name} fails its Charisma save. Every cultivated property "
             f"of its {item['name']} is suppressed until the start of {user.display_name}'s next turn; the item remains.",
             (target,))
        return
    by_prop = {prop["key"]: prop for prop in item["properties"]}
    chosen = _ask(ctx, target, "empty_palm_property", list(by_prop),
                  labels={key: by_prop[key]["name"] for key in by_prop}, preferred=list(by_prop)[:1],
                  prompt=(f"Empty Palm — Hollow the Weapon: {target.display_name} succeeds on its Charisma save and loses "
                          f"one named active property of its {item['name']} until the end of this turn. "
                          "Choose which property."))
    prop = by_prop[chosen[0]] if chosen else item["properties"][0]
    _hollow_property(ctx, target, item, prop, until="end")
    note(engine, ctx.source, user,
         f"Empty Palm — Hollow the Weapon: {target.display_name} succeeds on its Charisma save; only "
         f"{prop['name']} is suppressed, until the end of the current turn.", (target,))


def _hollow_property(ctx: Any, target: Any, item: dict[str, Any], prop: dict[str, Any], *, until: str) -> None:
    """Record one suppressed property as engine-swept state (nothing is destroyed or moved)."""
    from . import end_effect
    from .effect_durations import token

    engine, user, source = ctx.engine, ctx.actor, ctx.source
    expiry = (token("start", user.entity_id, int(user.turns_started) + 1) if until == "start"
              else token("end", user.entity_id, int(user.turns_started)))
    if "instance_id" in prop:
        live = target.conditions.get(prop["instance_id"])
        if live is not None:
            end_effect.suppress(target, "condition", prop["instance_id"], live,
                                rounds=1 if until == "start" else 0, by=user, engine=engine, boundary=until)
        return
    data = {"item": item["name"], "property": prop["name"], "source_cl": int(ctx.numbers.get("cl") or 1),
            "label": (f"Empty Palm — Hollow the Weapon: {target.display_name}'s {item['name']} cannot use "
                      f"{prop['name']} " + ("until the start of your next turn." if until == "start"
                                            else "until the end of this turn."))}
    if prop.get("action"):
        data["disables_action"] = str(prop["action"]).split("#", 1)[0]
    if prop.get("shield"):
        data["shield_item"] = prop["shield"]
    engine._apply_condition(target, HOLLOWED_ITEM, source, user.entity_id, expires_on=expiry, data=data)


@hook("ac")
def hollowed_shield(engine: Any, target: Any) -> int | None:
    """A hollowed Shield's Shield Bonus stops applying while Empty Palm's item suppression lasts."""
    from .. import armour

    key = armour.shield_item_key(engine, target)
    if key is None or not any(
            condition.condition_id == HOLLOWED_ITEM and (condition.data or {}).get("shield_item") == key
            for condition in target.conditions.values()):
        return None
    bonus = armour.shield_bonus_earning(engine, target)
    return -bonus if bonus else None


# ------------------------------------------------------------------------------------------------ printed damage type
@hook("damage_type_choice")
def force_or_void(ctx: Any, kinds: list[str], targets: list[Any]) -> str | None:
    """The printed "Force or Void": a player chooses; a computer-controlled seat leaves the engine's own pick."""
    if not _owns(ctx) or len(kinds) < 2:
        return None
    from .choice_prompt import action_context
    from .needle import ask
    from .teleport_steps import player_controls
    from ..target_knowledge import located

    if not player_controls(ctx.engine, ctx.actor):
        return None
    if "empty_palm_damage_type" in ctx.damage_cache:
        return ctx.damage_cache["empty_palm_damage_type"]
    known = [target for target in targets if located(ctx.engine, ctx.actor, target)]
    audience = ", ".join(target.display_name for target in known) or "the creature this hit reached"
    presentation = action_context(ctx.engine, ctx.actor, ctx.action.source_definition_id,
                                  known[0] if known else ctx.actor, action=ctx.action)
    picked = ask(ctx.engine, ctx.intent, "TECHNIQUE_USE", ctx.actor, CHOICE + "empty_palm_damage_type", list(kinds),
                 labels={kind: kind.title() + " damage" for kind in kinds}, preferred=list(kinds)[:1],
                 name=ctx.action.display_name + " damage", feature_id=EMPTY_PALM, prompt_context=presentation,
                 prompt=(f"{ctx.action.display_name}: choose the damage type for {audience}: "
                         f"{' or '.join(kind.title() for kind in kinds)}. The hit deals 4d8 + your Qi Cultivation key "
                         "ability modifier; this choice adds no cost beyond the 3 Qi the Action already paid."))
    ctx.damage_cache["empty_palm_damage_type"] = picked[0] if picked else kinds[0]
    return ctx.damage_cache["empty_palm_damage_type"]
