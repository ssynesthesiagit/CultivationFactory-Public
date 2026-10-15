"""Weapons Sphere talents (automation lane AUTO21): Breaking, the item rattle and the Flexible pull-back.

Every behaviour here is owned by one compiled row of the ``weapons_talent`` block
(``combat/rules/feature_blocks.d/auto21_weapons.json``); a creature without the row gets nothing, and a fight
saved before this file existed is unchanged. Shared helpers: ``talent``/``owners`` (whose printed row this actor
compiled, and which fighters hold one), ``item_row``/``delivered_weapon``/``held_weapon``/``holds_item``/``grip_weapon``/``weapon_words`` (what a
creature is holding and what tags it carries), ``sub_context`` (a Context for a rider that runs after this attack),
``lower_armor_class`` (the printed "that defensive bonus is 2 lower" row), ``method_used_this_turn``/``uses_breaking_method``
(whether this turn's one Weapon Method is spent, and whether the hit being resolved actually ran Breaking Method),
``committed_damage_this_hit`` (the damage this one hit really took off its target) and the ``weapon_method_breaking``
effect (Breaking Method itself), which Break the Guard uses. combat/ext/weapon_methods.py holds Breaking Method's own
row, read from combat/rules/weapon_specials.json, so the table's Breaking and the compiler's "+ Breaking" button are
one implementation.

Break the Guard (tianxia.talent.weapons.break_the_guard)
    "When you hit a creature benefiting from a shield, parry, guard stance, weapon ward, or similar defensive
    state, you may expend Martial Focus to use Breaking Method even if your weapon does not have a qualifying tag.
    If the hit deals damage, the target must make a Strength saving throw. On a failure, reduce one such defensive
    bonus by 2 until the start of your next turn."
    Asked after a weapon hit that actually took hit points or temporary hit points off a creature with a defensive
    bonus (its Shield bonus it still earns, or an Armor Class bonus of its own), and only while this turn's one
    Weapon Method is still unspent: the printed use is a Weapon Method like any other, so the rule waives the
    weapon's tag and nothing else. "If the hit deals damage" is read from the engine's own committed-damage
    notification for this hit (``committed_damage_this_hit``), so immunity, Resistance rounding or a fully absorbed
    packet that ends at 0 is no hit that deals damage, and with Extra Attack each hit is judged on its own damage
    rather than on an earlier hit of the same attack. Breaking Method is this table's own (your Proficiency Bonus
    added to the damage, in the weapon's own damage type) and runs through the shared Weapon Method execution, so it
    costs the printed 1 Martial Focus and is refused exactly as the compiler's own Breaking button is. The failed save
    lowers that creature's Armor Class by 2 through the general negative Armor Class row below until the start of the
    wielder's next turn (a parry or guard stance is an Armor Class number here, so "one such defensive bonus" is
    taken off that number).

Iron Against Iron (tianxia.talent.weapons.iron_against_iron)
    "When you use Breaking Method against a weapon, shield, or object held by a creature, the holder makes a Strength
    saving throw. On a failure, the item is rattled, cracked, caught, or driven out of line. Until the start of your
    next turn, attacks made with that item suffer a -2 penalty."
    Runs only where Breaking Method actually ran on this very hit: the ``after_hit_effects`` seam reads the engine's
    own record of the Weapon Methods this strike executed (``uses_breaking_method``), so an ordinary hit answers no,
    and the second hit of a "+ Breaking" Extra Attack -- where the table's one-per-turn limit refused the method --
    answers no as well. The player then picks which of the creature's items the hit aimed at. A weapon it carries gets
    ``item_disrupted``: attacks made with that weapon are 2 lower until the start of the wielder's next turn. A carried
    shield makes no attacks at all, so the printed -2 has nothing to sit on: the holder still makes the Strength save
    and the shield is recorded as rattled, but no number changes, and both the prompt and the typed rider say so. A
    save and a rattle happen only on a failure, which is what the printed rule says. The printed "does not destroy
    magic items ... unless the GM allows it" stays with the GM: nothing here ever destroys or removes an item.

Weapon-Breaking Retort (tianxia.talent.weapons.weapon_breaking_retort)
    "When a creature misses you with a melee weapon attack, you may use your Reaction and expend Martial Focus to make
    one weapon attack against the attacking weapon, shield, or limb.
    On a hit, deal normal damage. If the target is a weapon or shield, apply Breaking Method without additional cost."
    The Reaction, its price and its attack are the authority entry's own compiled reaction row, and its hit deals the
    printed normal damage. Breaking Method is not applied automatically. The printed attack is aimed "against the
    attacking weapon, shield, or limb", and this table cannot aim a weapon attack at a carried item or name a limb as
    its target: the attack is made against the creature, and whether the thing it struck is a weapon or a shield is the
    player's call at the table, not something a creature's possession of a weapon can answer. So the rider stays with
    the player. Should a row ever reach the shared ``weapon_method_breaking`` effect with that choice made, it runs
    through the table's own Weapon Method execution -- your Proficiency Bonus in your own weapon's damage type, for
    no second Martial Focus -- and Iron Against Iron's record notices that Breaking use like any other.

Soft Weapon Discipline (tianxia.talent.weapons.soft_weapon_discipline)
    "You no longer suffer Disadvantage from ordinary close-quarters use of Flexible weapons. When you miss with a
    Flexible weapon attack, you may choose to pull the weapon back safely and avoid exposing yourself. Until the start
    of your next turn, the next opportunity attack against you has Disadvantage."
    The first sentence removes nothing: this table never applies a Disadvantage for using a Flexible weapon at close
    quarters. The second is the ``pulled_back`` condition, spent by the first Opportunity Attack made against the
    owner (``attack_mode`` answers "DISADVANTAGE" and an evented ATTACK_ROLLED removes it).

Formation Weapon Drill (tianxia.talent.weapons.formation_weapon_drill)
    "When you wield a Reach, Polearm, Staff, Fork, Halberd, or Long weapon, allies within 5 feet of you gain Advantage
    on ability checks or saving throws made to avoid being forcibly moved through your threatened area."
    Not automated: this table resolves being pushed, pulled or knocked down as one saving throw wherever the creature
    stands and keeps no path for the movement, so it cannot tell whether the forced movement passes through the
    owner's threatened area. Granting the benefit to every nearby ally anyway would hand out a printed protection the
    trigger never established, so the talent keeps its printed text: no compiled row, no hook and no rider.

Concealed Carry Method (tianxia.talent.weapons.concealed_carry_method)
    "Once per combat, when you draw a Concealed or Hidden weapon against a creature that did not know you had it, you
    may use Hidden Method without counting against your once-per-turn Weapon Method limit."
    Not automated: the once-per-turn Weapon Method is this table's own (combat/typed_executor.py block_weapon_method),
    and it refuses a second one with no allowance query for a talent to spend. This module holds no row for it and no
    hook, so the talent keeps its printed rider until the core grows that allowance seam.

Shifting Grip Scripture (tianxia.talent.weapons.shifting_grip_scripture)
    "When wielding a Versatile, Staff, Polearm, Flexible, or Variable Reach weapon, you may change its handling mode at
    the start of each of your turns. Choose one: Close Grip. You may attack adjacent creatures without penalty. Long
    Grip. Increase reach by 5 feet until the start of your next turn, but attacks against adjacent creatures have
    Disadvantage. Guard Grip. You gain +1 AC until the start of your next turn, but your speed is reduced by 5 feet."
    A free choice at the start of the owner's turn (asked on the player's turn, chosen by an AI creature on its own),
    kept as the ``shifting_grip`` condition until the next such choice and naming the weapon it was chosen for: every
    reader checks that this fighter is still holding that weapon, so putting it away or swapping it ends the benefit
    at once instead of leaving a grip that follows nobody, and Long Grip's reach and Disadvantage are offered only to
    an attack made with that same weapon, because a grip is a way of holding one weapon. Close Grip is the weapon's
    ordinary reach and no penalty;
    Long Grip and Guard Grip carry their printed numbers until the start of the owner's next turn through the general
    ``attack_reach_bonus`` query, this module's ``ac``, ``speed`` and ``attack_mode`` hooks.
"""
from __future__ import annotations

from typing import Any

from . import effect, hook

BLOCK = "weapons_talent"
FOCUS = "resource:core.martial_focus"
ITEM_DOWN = "condition:typed.weapons_item_disrupted"
PULLED_BACK = "condition:typed.weapons_pulled_back"
GRIP = "condition:typed.weapons_shifting_grip"

GRIP_PROPERTIES = ("versatile", "staff", "polearm", "flexible", "variable reach")


# ------------------------------------------------------------------------------------------------ shared queries
def talent(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    """The actor's compiled Weapons talent row of this kind, or None (it does not own the talent)."""
    from .passive_rows import row_of

    return None if actor is None else row_of(engine, actor.entity_id, BLOCK, kind)


def owners(engine: Any, kind: str) -> list[Any]:
    """Every active fighter that compiled this Weapons talent row."""
    rows = getattr(engine, "typed_passive_rows", {}) or {}
    return [actor for actor_id, owned in sorted(rows.items())
            if (actor := engine.state.actors.get(actor_id)) is not None and actor.active
            and any(row.get("block") == BLOCK and row.get("kind") == kind for row in owned)]


def item_row(typed: dict[str, Any]) -> dict[str, Any]:
    """A typed action's delivered item as a dictionary, whichever shape the compiler wrote it in.

    A weapon attack carries the item's numbers (``{"damage_type": ..., "implement_id": ...}``); some rows carry only
    the item id string, with the numbers beside it under ``weapon_damage_type``/``source``.
    """
    weapon = (typed or {}).get("weapon")
    if isinstance(weapon, dict):
        return dict(weapon)
    if isinstance(weapon, str) and weapon:
        return {"implement_id": weapon, "damage_type": (typed or {}).get("weapon_damage_type"),
                "damage_types": [(typed or {}).get("weapon_damage_type")] if (typed or {}).get("weapon_damage_type") else [],
                "weapon_family": (typed or {}).get("weapon_family"), "properties": (typed or {}).get("properties")}
    return {}


def weapon_words(ctx: Any) -> tuple[set[str], str]:
    """The delivered item's property words and its weapon family words, lowercased (empty for a bare attack)."""
    weapon = item_row(getattr(ctx, "typed", None) or {})
    properties = str(weapon.get("properties") or "").lower()
    family = str(weapon.get("weapon_family") or "").lower()
    words = {word for word in properties.replace(",", " ").split() if word}
    return words, family


def delivered_weapon(ctx: Any) -> dict[str, Any]:
    """The item this typed attack actually delivers, or {} (an unarmed strike, a spell, a thrown object)."""
    from .weapon_hits import is_weapon_hit

    typed = getattr(ctx, "typed", None) or {}
    attack = next((row for row in typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == "attack"), {})
    weapon = item_row(typed)
    return weapon if weapon and is_weapon_hit(ctx, attack) else {}


def held_weapon(engine: Any, actor: Any) -> dict[str, Any]:
    """One weapon the actor is holding, as ``{implement_id, name, family, properties}`` (the strongest, or {} when
    barehanded). Family and properties come from the item catalogue, which is where the printed weapon lives.

    Shared by Break the Guard's weapon words, Shifting Grip Scripture's choice of a weapon to change the handling of,
    and Iron Against Iron's choice of the item a hit landed on.
    """
    from factory_authoring.starting_kits import item_definition
    from ..weapon_delivery import available_weapons
    from .hand_occupancy import weapon_allowed

    best = None
    for action in available_weapons(engine, actor).values():
        typed = (action.parameters or {}).get("typed") or {}
        weapon = item_row(typed)
        implement = str(weapon.get("implement_id") or "")
        if not implement or weapon_allowed(engine, actor, action) is False:
            continue
        catalogue = item_definition(implement)
        row = {"implement_id": implement, "name": action.display_name,
               "family": str(catalogue.get("weapon_family") or weapon.get("weapon_family") or "").lower(),
               "properties": str(catalogue.get("properties") or weapon.get("properties") or "").lower(),
               "damage_type": weapon.get("damage_type"),
               "damage_types": weapon.get("damage_types") or ([weapon["damage_type"]] if weapon.get("damage_type") else [])}
        if best is None or int(action.parameters.get("expected_damage") or 0) > best[0]:
            best = (int(action.parameters.get("expected_damage") or 0), row)
    return best[1] if best else {}


def holds_item(engine: Any, actor: Any, implement_id: str) -> bool:
    """Whether this fighter is still holding that one item, right now.

    ``available_weapons`` is what the fighter's own actions list as its weapons and ``weapon_allowed`` is the hand
    check the table already trusts for them, so a weapon that was dropped, stowed or disarmed answers False. Shared
    by Shifting Grip Scripture, whose handling modes belong to the weapon they were chosen for.
    """
    from ..weapon_delivery import available_weapons
    from .hand_occupancy import weapon_allowed

    wanted = str(implement_id or "")
    if not wanted:
        return False
    for action in available_weapons(engine, actor).values():
        weapon = item_row((action.parameters or {}).get("typed") or {})
        if str(weapon.get("implement_id") or "") == wanted and weapon_allowed(engine, actor, action) is not False:
            return True
    return False


def sub_context(ctx: Any, target: Any, source: str) -> Any:
    """A Context aimed at ``target`` for a rider that runs after this attack, carrying this fighter's save DC.

    This rider is part of the hit that asked for it, so it inherits that hit's own strike record
    (typed_executor.strike_record) exactly as the engine's own child contexts do. Without it the rider's Weapon Method
    would be written to the engine-level fallback instead, where the next nested strike clears it before anything can
    read it back, and a printed trigger naming the method (Iron Against Iron) would miss a method that really ran.
    """
    from .. import typed_executor as te
    from .needle import numbers_of

    numbers = {**numbers_of(ctx.engine, ctx.actor), "save_dc": int(ctx.numbers.get("save_dc") or 10)}
    typed = {**ctx.typed, "source": source, "numbers": numbers, "riders": []}
    return te.Context(ctx.engine, ctx.actor, ctx.action, getattr(ctx.engine, "_active_intent", None), typed, [target], target, {},
                      strike_record=getattr(ctx, "strike_record", None))


def say(engine: Any, source: str, actor: Any, text: str, target_ids: tuple[str, ...] = ()) -> None:
    engine._append_event("PASSIVE_TRIGGERED", source, actor_id=actor.entity_id, target_ids=target_ids,
                         payload={"trigger": text, "text": text})


def focus_held(actor: Any) -> bool:
    """Whether this fighter is holding any Martial Focus, the printed price of Break the Guard's Weapon Method."""
    return FOCUS in (actor.resources or {}) and int(actor.resources.get(FOCUS, 0)) > 0


# ------------------------------------------------------------------------------------------------ ownership
@hook("compile_block")
def weapons_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """One passive row per Weapons talent this table automates (combat/rules/feature_blocks.d/auto21_weapons.json)."""
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2),
             "cl": int(numbers.get("cl") or 1), **({"keeps_compiling": True} if spec.get("keeps_compiling") else {})}]


# ------------------------------------------------------------------------------------------------ a lower Armor Class
def lower_armor_class(evidence: str, amount: int = 2) -> dict[str, Any]:
    """The general typed row for "that defensive bonus is 2 lower until the start of your next turn".

    This table keeps a Shield bonus, a parry and a guard stance as one Armor Class number, so the printed
    "reduce one such defensive bonus by 2" is a negative ``ac_bonus`` modifier -- the engine's own row -- rather
    than a second way to lower Armor Class. "Until the start of your next turn" is the wielder's own next turn
    (the engine's ``START_OF_SOURCE_NEXT_TURN``), which is what this row expires at.
    """
    return {"type": "ac_bonus", "applies_to": "target", "amount": -int(amount),
            "expires_on": "START_OF_SOURCE_NEXT_TURN", "evidence": evidence}


# ------------------------------------------------------------------------------------------------ Breaking Method
METHOD_TURN_FLAG = "weapon_method"


def method_used_this_turn(actor: Any) -> bool:
    """Whether this fighter has already spent this turn's one Weapon Method.

    That limit is the table's own (typed_executor.block_weapon_method marks ``turn_flags["weapon_method"]``), so a
    printed extra use of a Weapon Method asks this before offering itself rather than quietly making a second one.
    """
    return bool((getattr(actor, "turn_flags", None) or {}).get(METHOD_TURN_FLAG))


def _weapon_method_rows(ctx: Any) -> list[dict[str, Any]]:
    """The Weapon Method rows this attack's own compiled effect carries (the compiler's "+ Breaking" buttons)."""
    typed = getattr(ctx, "typed", None) or {}
    return [row for effect in typed.get("effects") or [] if isinstance(effect, dict) and effect.get("type") == "attack"
            for row in effect.get("on_hit") or [] if isinstance(row, dict) and row.get("type") == "weapon_method"]


def attack_uses_weapon_method(ctx: Any) -> bool:
    """Whether the attack being resolved already applies a Weapon Method of its own (the fighter chose one with this
    attack). The table allows one per turn, so a printed extra use is not offered on top of it."""
    return bool(_weapon_method_rows(ctx))


def uses_breaking_method(ctx: Any, target: Any) -> bool:
    """Whether this very hit actually ran Breaking Method.

    Asked by Iron Against Iron's printed trigger ("When you use Breaking Method against a weapon, shield, or object
    held by a creature"), from the ``after_hit_effects`` seam, where the engine's per-strike record already holds
    every Weapon Method that executed on this hit. The record is proof of execution, not of selection: an ordinary
    weapon attack ran no method and answers False, and so does the second hit of a "+ Breaking" Extra Attack, where
    the table's one-per-turn limit refused the row. Both printed users of the method are covered, because
    Break the Guard's paid use also goes through the table's own Weapon Method execution.
    """
    from ..typed_executor import executed_weapon_methods
    from .weapon_methods import damage_types_of, used_breaking

    kinds = damage_types_of(delivered_weapon(ctx))
    return any(used_breaking(entry.get("effects") or [], kinds)
               for entry in executed_weapon_methods(ctx, target))


@effect("weapon_method_breaking")
def weapon_method_breaking(ctx: Any, row: dict[str, Any]) -> None:
    """Breaking Method as this table states it, through the table's own Weapon Method execution: your Proficiency
    Bonus added to the damage, of the weapon's type.

    The effects come from combat/ext/weapon_methods.py, which reads the owner's Breaking row out of
    combat/rules/weapon_specials.json -- the same entry the weapon's own "+ Breaking" button is built from -- so
    there is one implementation of the method rather than two that can drift apart. The damage type is the
    delivered weapon's own, never guessed. The rows are handed to ``weapon_method``
    (typed_executor.block_weapon_method) instead of being dealt here, so the table's one Weapon Method per turn
    covers this printed extra use too: spent this turn, the execution is refused and this row does nothing at all,
    exactly as it does for the compiler's button. ``cost`` is what the printed use charges for it (Break the
    Guard's 1 Martial Focus).
    """
    from .. import typed_executor as te
    from ..typed_executor import _default_subject
    from .weapon_methods import breaking_effects, damage_types_of

    subjects = [subject for subject in _default_subject(ctx, row, harmful=True) if subject.active]
    if not subjects:
        return
    cost = row.get("cost") if isinstance(row.get("cost"), dict) else {}
    effects: list[dict[str, Any]] = []
    if str(cost.get("resource") or "") == "martial_focus" and int(cost.get("amount") or 0) > 0:
        effects.append({"type": "spend_resource", "resource_id": FOCUS, "flat": int(cost["amount"]),
                        "applies_to": "self", "evidence": str(row.get("evidence") or "")})
    weapon = delivered_weapon(ctx) or held_weapon(ctx.engine, ctx.actor)
    effects += breaking_effects(damage_types_of(weapon),
                                str(row.get("evidence") or "Breaking Method: add your Proficiency Bonus to the damage"))
    te.run_effects(ctx, [{"type": "weapon_method", "first_hit_only": True, "effects": effects}])


def defensive_bonus(engine: Any, creature: Any) -> int:
    """How much of a defensive bonus this creature is actually keeping: the Shield bonus it still earns, plus any
    positive Armor Class bonus its own abilities grant it (a parry, a guard stance, a ward). 0 when it has none.

    The reduction itself is an ordinary ``armor_class`` modifier, never one of these bonuses, so a bonus this
    module has already taken away is not counted twice.
    """
    from .. import armour

    bonus = armour.shield_bonus_earning(engine, creature)
    bonus += sum(int(modifier.value) for modifier in creature.modifiers.values()
                 if modifier.target_field == "armor_class" and modifier.operation == "ADD" and int(modifier.value) > 0)
    return max(0, bonus)


COMMITTED_DAMAGE = "weapons_committed_damage"


@hook("damage_dealt")
def _note_committed_damage(ctx: Any, target: Any, amount: int) -> None:
    """Remember what this one strike really took off this one creature, for Break the Guard's "if the hit deals damage".

    The engine's own notification (combat/ext/__init__.py ``damage_dealt``) is scoped to this damage packet and
    already reports committed damage including temporary hit points, so immunity, Resistance rounding and a packet
    absorbed whole all read 0 and are no hit that deals damage.

    The amounts are kept in this strike's own record (typed_executor.strike_record), so they answer one hit alone:
    a second hit of an Extra Attack begins with an empty record and never inherits the first one's damage, a hit
    whose packets are all taken to nothing records nothing at all rather than falling back on the last strike, and a
    reaction attack resolving in the middle of this hit records into its own record instead of this one. Only a
    fighter that owns Break the Guard records anything; for anyone else the hook does nothing at all.
    """
    from ..typed_executor import strike_record

    record = strike_record(ctx)
    if record is None or talent(ctx.engine, ctx.actor, "break_the_guard") is None:
        return
    committed = record.setdefault(COMMITTED_DAMAGE, {})
    key = target.entity_id
    committed[key] = int(committed.get(key) or 0) + int(amount)


def committed_damage_this_hit(ctx: Any, target: Any) -> int:
    """The damage this strike committed against this creature, 0 when it committed none.

    Read (and cleared) by Break the Guard's ``after_hit``, so the printed offer is asked once per hit on the
    strength of that hit alone, whether that damage came from the attack's own packet or from a rider of it.
    """
    from ..typed_executor import strike_record

    record = strike_record(ctx)
    if record is None:
        return 0
    committed = record.get(COMMITTED_DAMAGE) or {}
    return int(committed.pop(target.entity_id, 0) or 0)


def _ask(ctx: Any, target: Any, key: str, label: str, prompt: str, feature: str) -> bool:
    """Ask the fighter (asked on a player's turn, decided by an AI creature on its own) whether to use this."""
    from .needle import CHOICE, ask, checkpoint_id

    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "WEAPONS", ctx.actor.entity_id, target.entity_id, key),
                 ctx.actor, CHOICE + "weapons_sphere", [key], labels={key: label}, allow_decline=True, automatic=True,
                 default="decline", target_id=target.entity_id, name=label, feature_id=feature, prompt=prompt)
    return bool(picked)


@hook("after_hit")
def break_the_guard(ctx: Any, target: Any, kind: str) -> None:
    """Break the Guard: spend Martial Focus on a guarded creature's hit for Breaking Method, then its Strength save."""
    from .. import typed_executor as te
    from .weapon_methods import damage_types_of

    row = talent(ctx.engine, ctx.actor, "break_the_guard")
    weapon = delivered_weapon(ctx)
    if row is None or kind != "weapon" or not weapon or not target.active or not focus_held(ctx.actor):
        return
    if method_used_this_turn(ctx.actor) or attack_uses_weapon_method(ctx):
        return  # the printed use is a Weapon Method: this turn's one is spent, or this attack already applies one
    if committed_damage_this_hit(ctx, target) < 1 or defensive_bonus(ctx.engine, target) < 1:
        return  # "If the hit deals damage": this hit took nothing off it, so there is no guard to break
    kind_name = damage_types_of(weapon)[0] if damage_types_of(weapon) else "Untyped"
    if not _ask(ctx, target, "break_the_guard", "Break the Guard: spend 1 Martial Focus",
                f"Break the Guard: your {ctx.action.display_name} hit {target.display_name}, which is guarding itself. "
                f"Spend 1 Martial Focus to break its guard: add your Proficiency Bonus to the damage ({kind_name}), then "
                f"{target.display_name} makes a Strength saving throw against your Weapon Method DC. On a failure its Armor "
                "Class is 2 lower until the start of your next turn.", str(row.get("feature_id"))):
        return
    sub = sub_context(ctx, target, str(row.get("feature_id")))
    te.run_effects(sub, [{"type": "weapon_method_breaking", "applies_to": "target",
                          "cost": {"resource": "martial_focus", "amount": 1},
                          "evidence": "Break the Guard: Breaking Method adds your Proficiency Bonus to the damage"}])
    if not method_used_this_turn(ctx.actor):
        return  # the shared Weapon Method execution refused it: nothing was paid and no guard was broken
    # The executed Weapon Method is now in the engine's record for this hit, which is how Iron Against Iron sees
    # that this hit used Breaking Method; nothing is marked here.
    te.run_effects(sub, [{"type": "save", "ability": "str", "dc": "technique_save_dc", "applies_to": "target", "harmful": True,
                          "on_fail": [lower_armor_class("Break the Guard: one of its defensive bonuses is 2 lower until the start of your next turn")],
                          "evidence": "Break the Guard: Strength saving throw against your Weapon Method DC"}])
    say(ctx.engine, str(row.get("feature_id")), ctx.actor,
        f"Break the Guard: {ctx.actor.display_name} breaks {target.display_name}'s guard with {ctx.action.display_name}.", (target.entity_id,))


def _breakable_items(engine: Any, target: Any) -> list[tuple[str, str]]:
    """The items this creature carries that a weapon hit could break, as (id, player label)."""
    from .. import armour

    items = [(item["implement_id"], f"its {item['name']}") for item in [held_weapon(engine, target)] if item.get("implement_id")]
    if armour.shield_bonus_earning(engine, target) > 0:
        items.append(("shield", "its carried shield"))
    return items


@hook("after_hit_effects")
def iron_against_iron(ctx: Any, target: Any, kind: str) -> None:
    """Iron Against Iron: a Strength save against the item a Breaking Method hit landed on; on a failure it fights 2 worse.

    Runs from ``after_hit_effects`` rather than ``after_hit`` because its printed trigger is about a Weapon Method
    that this hit executes: only after this hit's own on-hit rows have run does the engine's record say whether
    Breaking Method was actually used, so an Extra Attack's second hit is judged on its own method, not the first's.
    """
    from .. import typed_executor as te

    row = talent(ctx.engine, ctx.actor, "iron_against_iron")
    weapon = delivered_weapon(ctx)
    if row is None or kind != "weapon" or not weapon or not target.active:
        return
    if not uses_breaking_method(ctx, target):
        return  # printed "When you use Breaking Method": this hit ran no method, or the one it ran was not Breaking
    items = _breakable_items(ctx.engine, target)
    if not items:
        return
    chosen = items[0]
    if len(items) > 1:
        from .needle import CHOICE, ask, checkpoint_id

        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "IRON", ctx.actor.entity_id, target.entity_id),
                     ctx.actor, CHOICE + "weapons_sphere", [item for item, _ in items],
                     labels={item: f"Strike at {label}" for item, label in items}, allow_decline=True, automatic=True,
                     default="decline", target_id=target.entity_id, name="Iron Against Iron: which item did your hit land on?",
                     feature_id=str(row.get("feature_id")),
                     prompt=f"Iron Against Iron: your {ctx.action.display_name} broke {target.display_name}'s guard with Breaking "
                            "Method. Which of its items did the hit land on? Its holder then makes a Strength saving throw against "
                            "your Weapon Method DC. On a failure that item is rattled until the start of your next turn, and "
                            "attacks made with it are 2 lower. A shield makes no attacks, so rattling it changes no number; you "
                            "can still rattle it, and your table decides what that means.")
        if not picked:
            return
        chosen = next((item for item in items if item[0] == picked[0]), chosen)
    item_id, item_label = chosen
    # The printed consequence is "-2 on attacks made with that item", so it is read off the attacks actually made
    # with it (disrupted_item_attack matches the delivered implement). A shield makes no attacks, so the rattle is
    # recorded as a state the table can see and no number is invented for it.
    rattled: dict[str, Any] = {"type": "weapons_item_disrupted", "applies_to": "target", "item": item_id, "amount": 2,
                               "expires_on": "START_OF_SOURCE_NEXT_TURN",
                               "label": (f"{item_label} rattled: attacks made with it are 2 lower"
                                         if item_id != "shield" else
                                         f"{item_label} rattled: it makes no attacks, so nothing mechanical changes"),
                               "evidence": f"Iron Against Iron: attacks made with {item_label} are 2 lower until the start of your next turn"}
    sub = sub_context(ctx, target, str(row.get("feature_id")))
    te.run_effects(sub, [{"type": "save", "ability": "str", "dc": "technique_save_dc", "applies_to": "target", "harmful": True,
                          "on_fail": [rattled],
                          "evidence": "Iron Against Iron: its holder makes a Strength saving throw against your Weapon Method DC"}])
    say(ctx.engine, str(row.get("feature_id")), ctx.actor,
        f"Iron Against Iron: {ctx.actor.display_name}'s {ctx.action.display_name} lands against {item_label}; "
        f"{target.display_name} braces against it.", (target.entity_id,))


@effect("weapons_item_disrupted")
def item_disrupted(ctx: Any, row: dict[str, Any]) -> None:
    """One named item (a wielded weapon's id, or "shield") is rattled until the start of its holder's next turn.

    Shared by Iron Against Iron's weapon and shield cases. The printed consequence is "-2 on attacks made with that
    item", so the number is read where the attacks are (``disrupted_item_attack`` matches the delivered
    implement); a rattled shield makes no attacks and so changes no number. It is still recorded, with a label that
    says so, because the printed failure is the item being rattled and the table should see which item that was.
    """
    from ..typed_executor import _default_subject, effect_expiry

    amount = int(row.get("amount") or row.get("flat") or 0)
    item = str(row.get("item") or "")
    if not item:
        return
    for subject in _default_subject(ctx, row, harmful=True):
        if subject.active:
            ctx.engine._apply_condition(
                subject, ITEM_DOWN, ctx.source, ctx.actor.entity_id,
                expires_on=effect_expiry(ctx, row, subject, condition=True),
                data={"item": item, "amount": amount if item != "shield" else 0, "label": str(row.get("label") or item)})


@hook("attack_bonus")
def disrupted_item_attack(ctx: Any, actor: Any) -> int | None:
    """The -2 on attacks made with a rattled item (Iron Against Iron), read off the holder's own condition."""
    implement = str(item_row(getattr(ctx, "typed", None) or {}).get("implement_id") or "")
    if not implement:
        return None
    return next((-int((held.data or {}).get("amount") or 0) for held in actor.conditions.values()
                 if held.condition_id == ITEM_DOWN and str((held.data or {}).get("item") or "") == implement), None)


# ------------------------------------------------------------------------------------------------ Soft Weapon Discipline
def _flexible(ctx: Any) -> bool:
    """Whether the delivered weapon is Flexible (a whip, a chain, a sectional staff)."""
    words, family = weapon_words(ctx)
    return "flexible" in words or "flexible" in family


@hook("after_miss")
def soft_weapon_discipline(ctx: Any, target: Any) -> None:
    """Miss with a Flexible weapon: offered the printed pull-back, so the next Opportunity Attack is a bad bet."""
    row = talent(ctx.engine, ctx.actor, "soft_weapon_discipline")
    if row is None or not target.active or not _flexible(ctx) or not ctx.actor.active:
        return
    if not _ask(ctx, target, "soft_weapon_discipline", "Soft Weapon Discipline: pull the weapon back safely",
                f"Soft Weapon Discipline: your {ctx.action.display_name} missed {target.display_name} with a Flexible weapon. "
                "Pull it back safely: the next Opportunity Attack made against you has Disadvantage, until the start of your "
                "next turn.", str(row.get("feature_id"))):
        return
    ctx.engine._apply_condition(
        ctx.actor, PULLED_BACK, str(row.get("feature_id")), ctx.actor.entity_id,
        expires_on="START_OF_SOURCE_NEXT_TURN",
        data={"label": "Weapon pulled back safely: the next Opportunity Attack against you has Disadvantage"})
    say(ctx.engine, str(row.get("feature_id")), ctx.actor,
        f"Soft Weapon Discipline: {ctx.actor.display_name} pulls the weapon back safely after missing {target.display_name}.")


@hook("attack_mode")
def pulled_back(ctx: Any, target: Any) -> str | None:
    """Disadvantage on the next Opportunity Attack against a fighter that pulled its Flexible weapon back."""
    if getattr(ctx.engine, "_typed_oa_attacker", None) != ctx.actor.entity_id:
        return None
    return "DISADVANTAGE" if any(held.condition_id == PULLED_BACK for held in target.conditions.values()) else None


@hook("event")
def pull_back_spent(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The first Opportunity Attack made against the holder uses the printed Disadvantage up."""
    if event_type != "ATTACK_ROLLED" or getattr(engine, "_typed_oa_attacker", None) != kwargs.get("actor_id"):
        return
    for target_id in kwargs.get("target_ids") or ():
        holder = engine.state.actors.get(target_id)
        if holder is not None and any(held.condition_id == PULLED_BACK for held in holder.conditions.values()):
            engine._remove_condition(holder, PULLED_BACK, "system:weapons_sphere.pull_back_spent")


# ------------------------------------------------------------------------------------------------ Weapon-Breaking Retort
RETORT = "tianxia.talent.weapons.weapon_breaking_retort"
# The retort's Reaction, its price and its hit are the authority entry's own compiled row, and its hit deals the
# printed normal damage. "If the target is a weapon or shield, apply Breaking Method without additional cost" is
# not run here: the attack is aimed at a weapon, a shield or a limb, and this table cannot aim a weapon attack at a
# carried item or name a limb as its target, so it does not know what the retort struck. That choice is the player's
# at the table, and the typed rider says so.


# ------------------------------------------------------------------------------------------------ Shifting Grip Scripture
GRIPS = {
    "close": "Close Grip: attack creatures next to you normally",
    "long": "Long Grip: reach 5 feet farther, and Disadvantage against creatures next to you",
    "guard": "Guard Grip: 1 more Armor Class, and your Speed 5 feet lower",
}


def grip_weapon(engine: Any, owner: Any) -> dict[str, Any]:
    """The wielded weapon whose handling this fighter may change (Versatile, Staff, Polearm, Flexible or Variable
    Reach), or {} when it holds none."""
    weapon = held_weapon(engine, owner)
    words = f"{weapon.get('properties') or ''} {weapon.get('family') or ''}".lower()
    return weapon if any(mark in words for mark in GRIP_PROPERTIES) else {}


@hook("turn_start_choice")
def shifting_grip_scripture(engine: Any, actor: Any) -> None:
    """A free choice at the start of the owner's turn: which grip its handling-mode weapon is in.

    The condition remembers the weapon it was chosen for, because the printed modes are how that weapon is held.
    """
    row = talent(engine, actor, "shifting_grip_scripture")
    weapon = grip_weapon(engine, actor)
    if row is None or not weapon or not actor.active:
        return
    from .needle import CHOICE, ask, checkpoint_id

    options = list(GRIPS)
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "GRIP", actor.entity_id),
                 actor, CHOICE + "weapons_sphere", options, labels={name: label for name, label in GRIPS.items()},
                 allow_decline=False, automatic=True, target_id=actor.entity_id, default="first",
                 name="Shifting Grip Scripture: choose this turn's grip", feature_id=str(row.get("feature_id")),
                 prompt=(f"Shifting Grip Scripture: {actor.display_name} changes how {weapon['name']} is held. "
                         "Close Grip lets you attack creatures next to you normally, as usual. Long Grip reaches 5 feet "
                         f"farther with {weapon['name']}, but your own attacks with it against creatures next to you have "
                         "Disadvantage. Guard Grip adds 1 "
                         "Armor Class and takes 5 feet off your Speed. The grip lasts until the start of your next turn, "
                         "and only while you are still holding that weapon."))
    chosen = picked[0] if picked and picked[0] in GRIPS else "close"
    engine._apply_condition(actor, GRIP, str(row.get("feature_id")), actor.entity_id,
                            expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"grip": chosen, "item": str(weapon.get("implement_id") or ""),
                                  "label": f"Shifting Grip: {GRIPS[chosen]} until the start of your next turn"})
    say(engine, str(row.get("feature_id")), actor, f"Shifting Grip Scripture: {actor.display_name} sets {GRIPS[chosen]}.")


def _grip_held(engine: Any, actor: Any, name: str | None = None) -> Any:
    """This fighter's grip condition for mode ``name``, or None when it has none.

    The grip is bound to the weapon it was chosen for: a fighter that puts that weapon away, swaps it or is disarmed
    keeps no handling mode, because a grip is how a particular weapon is held. A grip saved before a weapon id was
    recorded has no binding and so contributes nothing, rather than following the fighter forever.
    """
    for condition in actor.conditions.values():
        if condition.condition_id != GRIP:
            continue
        data = condition.data or {}
        if name is not None and str(data.get("grip") or "") != name:
            continue
        item = str(data.get("item") or "")
        if item and holds_item(engine, actor, item):
            return condition
    return None


def _grip_weapon(engine: Any, actor: Any, implement_id: str, name: str | None = None) -> Any:
    """The grip condition for mode ``name`` only when this attack is the one the gripped weapon is making, else None.

    A handling mode is a way of holding one weapon, so both of Long Grip's own effects belong to that weapon and not
    to the fighter: the reach and the Disadvantage are offered to an attack made with the gripped item alone. A
    fighter gripping a jian and striking with another weapon, or barehanded, is holding the jian in some other way
    and gains nothing from the mode this turn. A grip with no recorded item never matches an attack.
    """
    held = _grip_held(engine, actor, name)
    if held is None:
        return None
    return held if str((held.data or {}).get("item") or "") == str(implement_id or "") else None


def _attack_weapon(action: Any) -> str:
    """The implement id the attack profile being queried delivers with, "" for a bare attack (an unarmed strike)."""
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    return str(item_row(typed).get("implement_id") or "")


@hook("attack_reach_bonus")
def long_grip_reach(engine: Any, actor: Any, action: Any, opportunity: bool) -> dict[str, Any] | None:
    """Long Grip's 5 extra feet of reach, through the general reach query (no attack is rewritten).

    The query only asks a melee attack, and it re-reads the grip condition's own source and expiry, so a fighter
    without the talent, without a handling-mode weapon, without a Long Grip or no longer holding the gripped weapon
    contributes nothing. The 5 feet belong to the gripped weapon: they are offered only to an attack profile that
    actually delivers that implement, so a fighter gripping a jian and attacking with another weapon, or barehanded,
    is not reaching with it.
    """
    held = _grip_weapon(engine, actor, _attack_weapon(action), "long")
    if held is None or talent(engine, actor, "shifting_grip_scripture") is None:
        return None
    return {"source_id": held.source_definition_id, "feet": 5, "condition_id": held.instance_id,
            "stacking_group": "shifting_grip"}


@hook("attack_mode")
def long_grip_disadvantage(ctx: Any, target: Any) -> str | None:
    """Long Grip: the holder's own attacks with that weapon against creatures next to it have Disadvantage.

    Matched on the implement this strike actually delivers, so the printed penalty lands on the gripped weapon's own
    attacks and not on the fighter's every attack: another weapon in the other hand, or an unarmed strike, is made
    with something else and is not disadvantaged by how the jian is held.
    """
    if talent(ctx.engine, ctx.actor, "shifting_grip_scripture") is None:
        return None
    weapon = delivered_weapon(ctx)
    if not weapon or _grip_weapon(ctx.engine, ctx.actor, str(weapon.get("implement_id") or ""), "long") is None:
        return None
    return "DISADVANTAGE" if ctx.engine._distance_actor_to_actor(ctx.actor, target) <= 5 else None


@hook("ac")
def guard_grip_armor_class(engine: Any, target: Any) -> int | None:
    """Guard Grip's 1 Armor Class, while its weapon is still held."""
    if talent(engine, target, "shifting_grip_scripture") is None:
        return None
    held = _grip_held(engine, target, "guard")
    if held is None:
        return None
    return int((held.data or {}).get("ac") or 1)


@hook("speed")
def guard_grip_speed(engine: Any, actor: Any) -> int | None:
    """Guard Grip's 5 feet off the holder's Speed, while its weapon is still held."""
    if talent(engine, actor, "shifting_grip_scripture") is None:
        return None
    held = _grip_held(engine, actor, "guard")
    if held is None:
        return None
    return -int((held.data or {}).get("speed_ft") or 5)
