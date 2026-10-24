"""What a character is wearing, and what that armour gives them, read in one place.

Who uses this module:

* ``combat.factory_compiler`` — the single Armor Class computation
  (``armor_class``) and the walking Speed (``speed_penalty_ft``).  The AC that
  lands on the compiled actor template is the same number every later reader
  shows, so the character sheet and the table never disagree.
* ``character_sheet.service`` — the owner-facing sheet's Armor Class and Speed
  (``sheet_facts``), which runs the same calls in the same order, so the sheet
  shows what the fight will use rather than the unarmored projection.
* anything else that needs to answer "what is this character wearing?" without
  re-reading the two different places a starting kit can hold armour.

A starting kit holds armour two ways, and both have always counted:

* ``resolved_treasure_armor`` — a graded treasure chassis the player was given,
  with a ``chassis`` record and a ``refinement_bonus``;
* ``items`` — plain entries in the pinned mundane equipment catalog, which is
  also where the starting kit's own Shield lives.

D&D 5.5e (2024) rules this module implements, in the owner's words where they
exist:

* Armour AC replaces the unarmored calculation; alternate AC calculations
  replace rather than stack ("Alternate AC calculations replace rather than
  stack. Use one applicable AC calculation.").  A character wearing body armour
  uses that armour's AC.  A feature that wants a different calculation says so
  itself and adds its own modifier; nothing here guesses at one.
* A character does not *wear* armour that is worse for them than going without
  it (``wearing``, the one decision every reader shares).  Armour that loses to
  the best unarmored calculation is CARRIED: it gives no AC, no Dexterity cap
  and no Strength requirement, and the unarmored calculation is what applies.
  A real player would not put it on, so the character does not either.
* A Shield grants +2 AC to a trained wielder, whichever slot it was stored in.
  The compile_shield_bonus hook seals permission in both the sheet and compiler.
  Whether a fighter still *has* theirs mid-fight is not a compile-time fact:
  ``combat/ext/shield_possession.py`` takes the +2 away through the ``ac`` hook
  when the fight's own state says the shield is no longer in their hands.
* Dexterity is capped by whatever the armour's printed formula caps it at.
* An armour's Strength requirement is a Speed requirement, not an AC one: below
  it the wearer is slowed by 10 feet.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# The printed AC of a body armour: "12 + Dex modifier (max +2)", "11 + Dex
# modifier", "16".  The catalog spells the cap "+2" and other sources spell it
# "2", so both are read; a formula this cannot read returns None and the caller
# reports it rather than guessing.
_ARMOUR_FORMULA = re.compile(
    r"^\s*(\d+)\s*(?:\+\s*Dex(?:\s*modifier)?(?:\s*\(\s*max\s*\+?\s*(\d+)\s*\))?)?",
    re.I,
)
# "Str 15" on a record, "—" where the armour asks for nothing.
_STRENGTH_REQUIREMENT = re.compile(r"Str(?:ength)?\s+(\d+)", re.I)

# D&D 5.5e: below the requirement, the wearer's Speed is reduced by 10 feet.
STRENGTH_SPEED_PENALTY_FT = 10
# D&D 5.5e: a trained wielder earns +2 AC from one equipped Shield.
SHIELD_AC_BONUS = 2


def catalog() -> dict[str, dict[str, Any]]:
    """The pinned mundane equipment catalog, keyed by item id."""
    from factory_authoring.starting_kits import _authorities

    return _authorities()[1]


def _worn_record(kit: dict[str, Any]) -> dict[str, Any] | None:
    """The body armour's catalog/authority record, or None when none is worn.

    A Shield is carried, not worn as body armour, so it is not returned here.
    Treasure chassis wins over a mundane item, matching the rest of compilation.
    """
    armor = kit.get("resolved_treasure_armor")
    if isinstance(armor, dict) and isinstance(armor.get("chassis"), dict):
        category = armor["chassis"].get("armor_category")
        if category and category != "shield":
            return dict(armor["chassis"])
    items = catalog()
    for item in kit.get("items") or []:
        record = items.get(item.get("item_id")) if isinstance(item, dict) else None
        category = (record or {}).get("armor_category")
        if category and category != "shield":
            return dict(record)
    return None


def armor_name(record: dict[str, Any] | None) -> str:
    """The armour's own name for a player-facing note ("Lacquered Leather")."""
    return str((record or {}).get("name") or (record or {}).get("item_id") or "this armour").strip()


def wearing(base_ac: int, kit: dict[str, Any], mods: dict[str, int]) -> dict[str, Any] | None:
    """The body armour the character actually puts on, or None when they carry it.

    Armour is worn only when it beats going without it.  ``base_ac`` is the best
    unarmored calculation already chosen for this character; the armour's own AC
    is computed here with the same printed formula and Dexterity cap the fight
    uses.  When the unarmored number is higher, the character carries the armour
    instead (``owner 2026-10-02``: "a real player wouldn't wear worse armor"), and
    the character is unarmored for every other rule that asks.

    Every reader asks this one question -- ``worn_armor_category``,
    ``strength_requirement``, ``armor_class`` and the sheet's "worn" marker all go
    through here, so the AC number, the Speed penalty and the sheet can never
    disagree about whether the armour is on.
    """
    record = _worn_record(kit)
    if record is None:
        return None
    formula = str(record.get("armor_class") or "")
    worn = _from_formula(formula, int(mods.get("DEX", 0)))
    if worn is None:  # an unreadable formula: wear it, and let armor_class report it
        return record
    # Refinement belongs to this armour's calculation. Include it when deciding
    # whether to wear the chassis; it cannot improve an unarmored calculation.
    treasure = kit.get("resolved_treasure_armor")
    treasure = treasure if isinstance(treasure, dict) else {}
    refinement = _refinement_bonus(kit) if (treasure.get("chassis") or {}).get("armor_category") != "shield" else 0
    return record if worn + refinement >= int(base_ac) else None


def carried_note(base_ac: int, kit: dict[str, Any], mods: dict[str, int]) -> str | None:
    """A plain sentence for the sheet when armour is carried rather than worn.

    "Carrying Lacquered Leather -- your unarmored defense (AC 19) is better than
    wearing it (AC 13)."  Names the armour, both numbers, and what the character
    is doing instead, with no internal ids.
    """
    record = _worn_record(kit)
    if record is None or wearing(base_ac, kit, mods) is not None:
        return None
    worn = _from_formula(str(record.get("armor_class") or ""), int(mods.get("DEX", 0)))
    if worn is None:
        return None
    return (f"Carrying {armor_name(record)} -- your unarmored defense (AC {int(base_ac)}) is better than "
            f"wearing it (AC {int(worn)}), so it gives you no Armor Class and no Armour penalties.")


def worn_armor_category(kit: dict[str, Any], base_ac: int | None = None,
                        mods: dict[str, int] | None = None) -> str | None:
    """The worn body armour's category ("light", "medium", "heavy"), or None.

    With ``base_ac`` and ``mods`` the caller gets the *worn* answer (armour
    carried because it is worse is not worn).  Without them this is the
    "is any body armour in the kit" question, kept for callers that only need
    the category the records carry.
    """
    record = wearing(base_ac, kit, mods) if base_ac is not None and mods is not None else _worn_record(kit)
    category = (record or {}).get("armor_category")
    return str(category) if category else None


def carries_shield(kit: dict[str, Any], owner_items: list[dict[str, Any]] | None = None) -> bool:
    """True when the kit holds a Shield, in either storage slot.

    ``owner_items`` is the owner-granted equipment store, which holds its own
    ``record``/``chassis`` shape.  ``fix/hands`` reads the same rows to decide
    whether a shield takes up a hand; passing them here too is what keeps the
    grip check and the AC number talking about the same shield.
    """
    if any(((row.get("record") or {}).get("chassis") or {}).get("armor_category") == "shield"
           for row in owner_items or [] if isinstance(row, dict)):
        return True
    armor = kit.get("resolved_treasure_armor")
    if isinstance(armor, dict) and (armor.get("chassis") or {}).get("armor_category") == "shield":
        return True
    items = catalog()
    return any(
        isinstance(item, dict)
        and (items.get(item.get("item_id")) or {}).get("armor_category") == "shield"
        for item in kit.get("items") or []
    )


def shield_ac_bonus(kit: dict[str, Any], owner_items: list[dict[str, Any]] | None = None) -> int:
    """The +2 AC a carried Shield gives."""
    return SHIELD_AC_BONUS if carries_shield(kit, owner_items) else 0


# ------------------------------------------------------------------------------------ mid-fight possession
# The Shield's +2 is folded into the compiled Armor Class (the sheet and the fight read that one number), so
# losing the shield mid-fight cannot change the compiled template: it is taken back through the ``ac`` hook.
# The three questions below are the single source for that, and the one place the numbers come from.

#: The condition a broken Shield puts on its owner (``combat/ext/shield_riders.py``, Sacrificial Shield).  Named
#: here so the plug-in that owns the Shield Bonus and the rider that breaks the shield cannot disagree about it.
BROKEN_SHIELD = "condition:typed.shield_broken"


def compiled_shield_bonus(engine: Any, actor: Any) -> int:
    """The Shield Bonus already inside this fighter's compiled AC (0 when they carry no shield).

    Read from the compiled ``shield_ac`` passive row the compiler records, so a fighter compiled before this
    existed, a monster with a stat block, and anyone without a shield all read 0 and are left alone.
    """
    rows = (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []) if actor is not None else []
    return sum(int(row.get("amount") or 0) for row in rows if row.get("block") == "shield_ac")


def shield_item_key(engine: Any, actor: Any) -> str | None:
    """The inventory key of the shield this fighter carries, or None.

    The compiler marks the shield row of the character's item list (``carrying.items[].shield``).  A fight saved
    before that marker existed has none, so this returns None and the fighter's AC is left exactly as it was.
    """
    from . import carry

    carrying = carry.carrying_of(engine, actor.entity_id) if actor is not None else None
    return next((str(item["key"]) for item in (carrying or {}).get("items") or []
                 if isinstance(item, dict) and item.get("shield") and item.get("key")), None)


def equipment_use_allowed(engine, actor, kind):
    """Pure equipment permission shared by native shield and weapon readers.

    No provider leaves legacy possession unchanged; false answers veto use but
    never transfer, destroy or drop an owned item.
    """
    from . import ext
    replies=ext.run_checkpoint('equipment_use_allowed',engine,actor,kind)
    if any(type(reply) is not bool for reply in replies):
        raise ext.CheckpointError('equipment_use_allowed must return bool or None')
    return False not in replies


def shield_bonus_earning(engine: Any, actor: Any) -> int:
    """The Shield Bonus this fighter is actually earning right now.

    Their compiled bonus unless the fight's own state says otherwise: the shield is marked in their item list and
    that item has left their hands, or the shield is broken.  A fighter whose shield cannot be *identified* --
    no item list at all (a hand-built actor in a test), or a fight saved before the compiler marked it -- keeps
    their bonus unless a persisted broken-shield condition says it was lost.

    Every source that takes the Shield Bonus away -- the shield being dropped, taken, or broken, or a talent that
    denies it -- subtracts from this, so no two of them can take the same +2 twice.
    """
    compiled = compiled_shield_bonus(engine, actor)
    if not compiled or actor is None or not equipment_use_allowed(engine,actor,'shield'):
        return 0
    from . import carry

    key = shield_item_key(engine, actor)
    if any(c.condition_id == BROKEN_SHIELD for c in actor.conditions.values()):
        return 0
    if key is None:  # no possession information; the broken condition was still checked above
        return compiled
    if carry.lost_to_another_hand(actor, key):
        return 0
    return compiled


def shield_bonus_lost(engine: Any, actor: Any) -> int:
    """The part of the compiled Shield Bonus the fighter is not earning (0 while they still have their shield)."""
    return max(0, compiled_shield_bonus(engine, actor) - shield_bonus_earning(engine, actor))


def sheet_ac_bonuses(sheet: dict[str, Any], kit: dict[str, Any], mods: dict[str, int],
                     passives: list[dict[str, Any]]) -> tuple[int, int]:
    """Resolve projected AC bonuses once for factory_compiler and sheet consumers.

    Statistic authority names each source and its required calculation. Those
    sources are awarded here rather than again as combat defense rows. Older
    sheets lacking provenance are resolved against the same sealed authority;
    unrelated bonuses remain intact. Returns (applicable bonus, armour-choice
    basis); calculation-dependent bonuses count when comparing unarmored AC
    with body armour. Saved bundles are never rewritten.
    """
    from pathlib import Path
    from projector.path_feature_statistics import load_path_feature_statistic_formulas
    from stage2.formulas import evaluate_formula

    ac = sheet["ability_scores_and_statistics"].get("armor_class") or {}
    if isinstance(ac, str):
        import json
        ac = json.loads(ac)
    if not isinstance(ac, dict):
        return 0, int(ac or 10)
    base = int(ac.get("base_value") or ac.get("value") or 10)
    delta = int(ac.get("value") or base) - base
    paths = sheet.get("path_and_subpath") or {}
    owned = set(paths.get("path_feature_record_ids") or [])
    owned.update(row.get("feature_id") for row in paths.get("earned_feature_occurrences") or [] if isinstance(row, dict))
    rules = load_path_feature_statistic_formulas(Path(__file__).resolve().parents[1])["rules"]
    generation = ac.get("generation")
    if isinstance(generation, dict) and 'calculation_feature_id' in generation:
        chosen = generation.get("calculation_feature_id")
        folded = sum(int(row.get("bonus") or 0) for row in generation.get("always_on_bonuses") or [])
    else:
        # Historical sheets omitted provenance. Match their published base to
        # the printed formulas, preserving baseline preference on ties.
        chosen = None
        if base != 10 + int(mods.get("DEX", 0)):
            context = {"ability_modifiers": mods, "pb": int((sheet.get("identity") or {}).get("proficiency_bonus") or 2)}
            chosen = next((r["feature_id"] for r in rules if r["kind"] == "base_ac_calculation"
                           and r["feature_id"] in owned and int(evaluate_formula(r["formula"]["root"], context).value) == base), None)
        folded = sum(int(r.get("bonus") or 0) for r in rules if r["kind"] == "ac_bonus" and r["feature_id"] in owned
                     and r.get("requires_base_calculation_feature_id") in (None, chosen)) if "value" in ac else 0
        folded = min(max(0, delta), folded)
    sources = {r["feature_id"] for r in rules if r["kind"] == "ac_bonus"}
    passives[:] = [row for row in passives if not (row.get("feature_id") in sources and row.get("block") == "defense" and row.get("kind") == "ac")]
    eligible = [r for r in rules if r['kind'] == 'ac_bonus' and r['feature_id'] in owned
                and r.get('requires_base_calculation_feature_id') in (None, chosen)]
    choice_base = base + sum(int(r.get('bonus') or 0) for r in eligible if r.get('requires_base_calculation_feature_id'))
    worn = wearing(choice_base, kit, mods) is not None
    applicable = sum(int(r.get("bonus") or 0) for r in rules if r["kind"] == "ac_bonus" and r["feature_id"] in owned
                     and (not r.get("requires_base_calculation_feature_id") or
                          (not worn and r["requires_base_calculation_feature_id"] == chosen)))
    return delta - folded + applicable, choice_base


def _refinement_bonus(kit: dict[str, Any]) -> int:
    armor = kit.get("resolved_treasure_armor")
    return int(armor.get("refinement_bonus") or 0) if isinstance(armor, dict) else 0


def _from_formula(formula: str, dex: int) -> int | None:
    match = _ARMOUR_FORMULA.match(str(formula or ""))
    if not match:
        return None
    if not re.search(r"\bdex\b", formula, re.I):
        return int(match.group(1))
    value = int(match.group(1)) + dex
    return min(value, int(match.group(1)) + int(match.group(2))) if match.group(2) else value


def alternate_ac_calculations(passives: Iterable[dict[str, Any]] | None, mods: dict[str, int]) -> list[int]:
    """The Armor Class calculations a character's compiled "defense" rows offer besides the sheet's own.

    A feature that prints "while you are wearing no armor and not using a shield, your Armor Class equals
    10 + your Dexterity modifier + ..." states an alternate calculation, not a bonus: owner amendment R1
    ("Alternate AC calculations replace rather than stack. Use one applicable AC calculation."), so it
    must not be added to whatever calculation the sheet already chose. Each such row carries the constant
    it starts from (``ac_base``), the ability modifier it reads (``ac_ability``) and the number its own
    feature adds (``amount``, already resolved from "pb"/"key_mod" at compile time); this returns those as
    whole numbers for :func:`armor_class` to choose between. Rows of every other kind -- including an
    ordinary "ac" bonus row -- are ignored, so a character without such a feature gets an empty list and
    nothing changes.
    """
    out: list[int] = []
    for row in passives or ():
        if str(row.get("kind")) != "ac_calculation":
            continue
        out.append(int(row.get("ac_base") or 0) + int(mods.get(str(row.get("ac_ability") or "DEX").upper(), 0))
                   + int(row.get("amount") or 0))
    return out


def armor_class(base_ac: int, kit: dict[str, Any], mods: dict[str, int], *,
                owner_items: list[dict[str, Any]] | None = None,
                always_on: int = 0,
                choice_ac: int | None = None,
                calculations: Iterable[int] | None = None,
                diagnostics: list[str] | None = None,
                breakdown: list[dict[str, Any]] | None = None,
                shield_override: int | None = None) -> int:
    """The character's Armor Class: the one computation, read by the sheet and the fight.

    ``base_ac`` is the unarmored calculation already chosen for the character
    (10 + Dexterity, or a Path's own alternate calculation).  Worn body armour
    *replaces* it rather than competing with it; a carried Shield adds its +2 on
    top of whichever calculation applied.  A treasure chassis's Refinement
    Bonus applies to body armour only while worn, and to a carried Shield.

    ``calculations`` are further whole Armor Class calculations this character
    qualifies for while unarmored -- a feature printing "your Armor Class equals
    10 + your Dexterity modifier + ..." -- from
    :func:`alternate_ac_calculations`.  One applicable calculation is used and the
    alternates replace rather than stack (owner amendment R1), so the highest of
    the sheet's own calculation and these applies; an explicit bonus
    (``always_on``) still applies after the calculation is chosen.  Worn body
    armour replaces them all, exactly as it replaces the unarmored calculation.

    ``always_on`` contains bonuses applicable to the selected calculation.
    ``choice_ac`` includes calculation-dependent bonuses when deciding whether
    body armour is better; those bonuses must not be carried over to worn armour.
    The compiler resolves source provenance with ``sheet_ac_bonuses`` first.
    """
    # Optional display seam for every armor calculation: report the terms from
    # this computation, without changing its result or writing to fight state.
    alternates = [int(value) for value in calculations or ()]
    value = int(base_ac)
    unarmored = max([value, *alternates])
    # Worn armour replaces the unarmored calculation, so an alternate calculation counts when the character
    # decides what to wear; without one this is the same comparison the sheet and the compiler have always made.
    record = wearing(unarmored if choice_ac is None else max([int(choice_ac), *alternates]), kit, mods)
    if record is not None:
        formula = str(record.get("armor_class") or "")
        worn = _from_formula(formula, int(mods.get("DEX", 0)))
        if worn is None:
            if diagnostics is not None:
                diagnostics.append(f"Armour AC formula not read: {formula}")
        else:
            value = worn
    elif alternates:
        value = unarmored
    treasure = kit.get("resolved_treasure_armor")
    treasure = treasure if isinstance(treasure, dict) else {}
    refined_shield = (treasure.get("chassis") or {}).get("armor_category") == "shield"
    refinement = _refinement_bonus(kit) if record is not None or refined_shield else 0
    shield = shield_ac_bonus(kit, owner_items) if shield_override is None else shield_override
    if breakdown is not None:
        # Split only the formula this calculation successfully read. The Dex
        # contribution is the evaluated value minus its printed constant, so
        # display code does not implement a second cap/bonus calculation.
        printed = _ARMOUR_FORMULA.match(formula) if record is not None and worn is not None else None
        if printed is not None:
            constant = int(printed.group(1))
            breakdown.append({"source": armor_name(record), "value": constant})
            if "dex" in formula.lower():
                cap = f" (armor caps the bonus at +{printed.group(2)})" if printed.group(2) else ""
                breakdown.append({"source": f"Dexterity modifier{cap}", "value": value - constant})
        else:
            breakdown.append({"source": "unarmored calculation", "value": value})
        for source, bonus in (("standing bonuses", int(always_on)), ("armor refinement", refinement), ("shield", shield)):
            if bonus:
                breakdown.append({"source": source, "value": bonus})
    return value + int(always_on) + refinement + shield


def strength_requirement(kit: dict[str, Any], base_ac: int | None = None,
                         mods: dict[str, int] | None = None) -> int | None:
    """The worn armour's printed Strength requirement as a score, or None.

    Armour carried rather than worn asks for nothing: "no Armour penalties
    apply" includes the Strength requirement that costs Speed.
    """
    record = wearing(base_ac, kit, mods) if base_ac is not None and mods is not None else _worn_record(kit)
    match = _STRENGTH_REQUIREMENT.search(str((record or {}).get("strength") or ""))
    return int(match.group(1)) if match else None


def speed_penalty_ft(kit: dict[str, Any], strength_score: int, base_ac: int | None = None,
                     mods: dict[str, int] | None = None) -> int:
    """Walking Speed lost to the worn armour's Strength requirement (10 ft, 2024).

    Returns 0 when nothing worn has a requirement, when the wearer meets it, or
    when the armour is carried rather than worn.
    """
    required = strength_requirement(kit, base_ac, mods)
    if required is None:
        return 0
    return STRENGTH_SPEED_PENALTY_FT if int(strength_score) < required else 0


# ------------------------------------------------------------------------------ the character sheet
# ``sheet_facts`` is the one place the owner-facing sheet asks what armour this character fights in, so the
# sheet and the fight cannot disagree (the contract at the top of this module).  It calls the same public
# functions the compiler calls, in the same order, and adds no arithmetic of its own.


def _published_modifiers(sheet: dict[str, Any]) -> dict[str, int]:
    """The ability modifiers a sheet publishes, in the shape the compiler reads them."""
    rows = (sheet.get("ability_scores_and_statistics") or {}).get("abilities") or []
    return {str(row["ability"]): int(row.get("modifier") or 0)
            for row in rows if isinstance(row, dict) and row.get("ability")}


def _published_score(sheet: dict[str, Any], ability: str) -> int:
    """One published ability score, or the neutral 10 when the sheet does not record it."""
    rows = (sheet.get("ability_scores_and_statistics") or {}).get("abilities") or []
    for row in rows:
        if isinstance(row, dict) and str(row.get("ability") or "") == ability:
            try:
                return int(row.get("score"))
            except (TypeError, ValueError):
                return 10
    return 10


def _published_base_speed(sheet: dict[str, Any]) -> int:
    """The walking Speed a sheet publishes before any Armour penalty, as the compiler reads it."""
    speed = (sheet.get("ability_scores_and_statistics") or {}).get("speed") or {}
    try:
        return int(speed.get("walking_ft") or 30)
    except (TypeError, ValueError):
        return 30


def sheet_facts(sheet: dict[str, Any], kit: dict[str, Any]) -> dict[str, Any]:
    """The Armor Class and Speed this character actually fights with, read the way the fight reads them.

    Who uses this: ``character_sheet/service.py``, building the owner-facing sheet.  The sheet used to
    publish only the unarmored calculation and the unpenalized Speed, so a character who put on heavy
    armour saw a number the table never used (AUDIT9b NEW-1 and NEW-2).  This is the same call sequence
    ``combat.factory_compiler`` runs -- ``sheet_ac_bonuses`` resolves the AC bonuses, ``armor_class``
    applies worn armour, the Refinement Bonus and the Shield, ``speed_penalty_ft`` applies the Strength
    requirement -- so there is one derivation, not two.

    ``sheet`` is the published owner sheet, which is also the document the compiler reads, so the
    provenance, path features and ability scores read here are the ones the fight uses.  Returns:

    * ``armor_class`` -- the Armor Class the fight rolls against.
    * ``speed_ft`` -- the walking Speed the fight moves on.
    * ``unarmored`` -- the Armor Class this character would have with no body armour and no Shield.
    * ``worn`` / ``armor_name`` -- what the character has on, and what they are called.
    * ``armor_note`` / ``speed_note`` -- one plain sentence each for a player who knows only basic D&D.

    The two published numbers the compiler reads back (``armor_class.base_value``/``value`` and
    ``speed.walking_ft``) are deliberately NOT returned: the sheet publishes the derived values beside
    them rather than over them, because the compiler subtracts the Speed penalty and recovers the
    unarmored AC basis from those fields on the next compile.

    Inert for a character wearing nothing: the Armor Class is the sheet's own calculation, the Speed is
    unchanged, and no note is produced.
    """
    stats = sheet.get("ability_scores_and_statistics") or {}
    ac = stats.get("armor_class") or {}
    base_ac = int(ac.get("base_value") or ac.get("value") or 10)
    mods = _published_modifiers(sheet)
    always_on, choice_ac = sheet_ac_bonuses(sheet, kit, mods, [])
    from . import ext
    shield_bonus = ext.transform('compile_shield_bonus', shield_ac_bonus(kit),
        {'owner_sheet': sheet, 'owned_ids': None, 'kit': kit, 'owner_items': []})
    if type(shield_bonus) is not int or shield_bonus < 0:
        raise ValueError('compile_shield_bonus requires a nonnegative integer')
    value = armor_class(base_ac, kit, mods, always_on=always_on, choice_ac=choice_ac,
                        shield_override=shield_bonus)

    # The unarmored alternative a player is actually comparing against ("is the armour worth it?"). It is
    # the same two calls with an empty kit, not a second formula: no body armour, no Shield, no
    # Refinement Bonus, and the calculation-dependent AC bonuses that only apply while unarmored do.
    # ``armor_class.base_value`` cannot stand in for this -- it is the chosen calculation *before* the
    # standing bonuses are folded into ``value``, so a character with base 17 and active 18 is not
    # "unarmored 17".
    bare_always_on, bare_choice = sheet_ac_bonuses(sheet, {}, mods, [])
    unarmored = armor_class(base_ac, {}, mods, always_on=bare_always_on, choice_ac=bare_choice)

    base_speed = _published_base_speed(sheet)
    strength_score = _published_score(sheet, "STR")
    required = strength_requirement(kit, choice_ac, mods)
    penalty = speed_penalty_ft(kit, strength_score, choice_ac, mods)
    speed = max(0, base_speed - penalty)

    record = wearing(choice_ac, kit, mods)
    name = armor_name(record) if record is not None else None
    worn_ac = None
    if record is not None:
        parsed = _from_formula(str(record.get("armor_class") or ""), int(mods.get("DEX", 0)))
        worn_ac = int(parsed) if parsed is not None else None

    shield = carries_shield(kit)
    shield_part = f" and a Shield (+{shield_bonus})" if shield else ""
    if record is not None:
        printed = f" (Armor Class {worn_ac})" if worn_ac is not None else ""
        armor_note = f"Wearing {name}{printed}{shield_part} gives an Armor Class of {value}."
    else:
        armor_note = carried_note(choice_ac, kit, mods)
        if armor_note is None and shield:
            armor_note = (f"Not wearing body armour, so your unarmored Armor Class of {base_ac} applies"
                          f"{shield_part}: {value}.")

    speed_note = None
    if penalty and required is not None:
        speed_note = (f"{name} needs Strength {required} to wear and this character has {strength_score}, "
                      f"so it costs {penalty} ft of walking Speed: {speed} ft instead of {base_speed} ft.")
    return {
        "armor_class": value,
        "speed_ft": speed,
        "unarmored": unarmored,
        "worn": record is not None,
        "armor_name": name,
        "armor_note": armor_note,
        "speed_note": speed_note,
    }


__all__ = [
    "BROKEN_SHIELD",
    "SHIELD_AC_BONUS",
    "STRENGTH_SPEED_PENALTY_FT",
    "armor_class",
    "armor_name",
    "alternate_ac_calculations",
    "carried_note",
    "carries_shield",
    "catalog",
    "compiled_shield_bonus",
    "shield_ac_bonus",
    "shield_bonus_earning",
    "shield_bonus_lost",
    "shield_item_key",
    "sheet_facts",
    "speed_penalty_ft",
    "strength_requirement",
    "wearing",
    "worn_armor_category",
]
