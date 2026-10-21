"""Action cost alternatives (fix/action-cost-alternatives, hunt 3 bug 2).

"Cost: 15 Stamina or 15 CP" (Monkey Style's Great Sage Equal to Heaven, and 82 more actions, bonus actions and reactions) is paid in
ONE of the printed ways.  ``_costs`` used to read only the first, so a character without that pool -- Jia Fengshan (Qi), Jiang Xi
(Resonance), Shi Xunyun -- got a row it could never pay and forced fight F3-07 offered only END_TURN.  The compiler now reads every
printed way: the character pays in whichever it holds pools for.  A character that holds the pools for more than one way gets one row
per way (the first printed way keeps the ability's name and id, the others are suffixed "(15 Qi)", "(2 Stamina)", "(Martial Focus)"
like the modifier rows of test_cost_alternatives.py), because the engine pays a row's costs all together and a row cannot choose
between pools when it is used; a character with one pool, or whose ways all cost the same there, still gets one row.

The modifiers K left out are covered at the bottom: a Martial-Focus-only "2 Spear Resource or expend Martial Focus" (Army-Breaking
Thrust, Pinning Strike) and an extra-CP-only "spend 1 Stamina or 1 CP" (Body Resonance Strike, Nullifying Strike).
"""

import re

import pytest

from tests.test_cost_alternatives import (AXE_KIT, AXES, FAIL, QI_ONLY, QI_STAMINA, STAMINA_ONLY, SWORD, _bundle, _costs, _engine,
                                          _legal, _pay)

MONKEY, SOUND, VOID, SPEAR = "tianxia.sphere.monkey_style", "tianxia.sphere.sound", "tianxia.sphere.void", "tianxia.sphere.spear"
RESONANCE_ONLY = {"name": "Resonance", "maximum": 40}
SPEAR_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.qiang", "name": "Qiang (Spear)", "quantity": 1}]}}
POOLS = ("qi", "stamina", "resonance", "martial_focus")

GREAT_SAGE_KEY, GREAT_SAGE = "TAL_MONKEY_STYLE_GREAT_SAGE_EQUAL_TO_HEAVEN", "Great Sage Equal to Heaven"
GREAT_SAGE_QI = GREAT_SAGE + " (15 Qi)"
ROOT_HEWING_KEY, ROOT = "TAL_AXES_ROOT_HEWING_PASSAGE", "Root-Hewing Passage: "
ROOT_OPTIONS = ["Dense Roots", "Brambles", "Wooden Barricades", "Mundane Undergrowth", "Bone Thickets", "Waxy Growths"]
SEVER_KEY, SEVER = "TAL_AXES_SEVER_THE_STANDARD", "Sever the Standard"


def _paid(costs):
    """[(pool, amount)] of a row's costs, without the once-per-rest use counter."""
    return [(resource.split(".")[-1], amount) for resource, amount in costs if resource.startswith("resource:core.")]


def _ways(bundle, prefix):
    """display name -> [(pool, amount)] of every row whose name starts with ``prefix``."""
    return {name: _paid(costs) for name, costs in _costs(bundle).items() if name.startswith(prefix)}


def _lost(engine, name):
    """Use ``name``; the pools the actor lost (its once-per-rest counter left out), and the RESOURCE_SPENT events."""
    lost, events, _ = _pay(engine, name)
    return {pool: amount for pool, amount in lost.items() if pool in POOLS}, events


def _great_sage(**kw):
    return _bundle(MONKEY, [GREAT_SAGE_KEY], AXE_KIT, **kw)


# ------------------------------------------------------------------------------------ a pool the first way does not name


@pytest.mark.parametrize("primary,pool", [(QI_ONLY, "qi"), (STAMINA_ONLY, "stamina"), (RESONANCE_ONLY, "resonance")],
                         ids=["qi-only", "stamina-only", "resonance-only"])
def test_great_sage_is_legal_and_paid_in_the_pool_a_single_pool_character_holds(primary, pool):
    """"15 Stamina or 15 CP": a Qi or Resonance character has no Stamina, so it pays the 15 CP (hunt 3: it was never legal); a Stamina
    character pays the 15 Stamina.  One pool, one row, no suffix."""
    bundle = _great_sage(primary=primary)
    assert _ways(bundle, GREAT_SAGE) == {GREAT_SAGE: [(pool, 15)]}
    engine = _engine(bundle)
    assert GREAT_SAGE in _legal(engine)
    lost, events = _lost(engine, GREAT_SAGE)
    assert lost == {pool: 15}
    assert {event.payload.get("resource_id", "").split(".")[-1] for event in events} >= {pool}


def test_a_character_with_both_pools_gets_a_row_per_way_and_each_pays_only_its_own():
    """The first printed way (Stamina) keeps the name; the CP way is "(15 Qi)" for a character whose CP is Qi."""
    bundle = _great_sage()
    assert _ways(bundle, GREAT_SAGE) == {GREAT_SAGE: [("stamina", 15)], GREAT_SAGE_QI: [("qi", 15)]}
    assert _lost(_engine(bundle), GREAT_SAGE)[0] == {"stamina": 15}
    assert _lost(_engine(bundle), GREAT_SAGE_QI)[0] == {"qi": 15}


@pytest.mark.parametrize("held,legal", [
    ({}, {GREAT_SAGE, GREAT_SAGE_QI}),
    ({"qi": 0}, {GREAT_SAGE}),
    ({"stamina": 0}, {GREAT_SAGE_QI}),
    ({"qi": 14}, {GREAT_SAGE}),
    ({"stamina": 14}, {GREAT_SAGE_QI}),
    ({"qi": 0, "stamina": 0}, set()),
], ids=["both", "no-qi", "no-stamina", "14-qi", "14-stamina", "neither"])
def test_only_the_ways_the_actor_can_afford_are_legal(held, legal):
    """The menu (and the AI) only ever sees the ways that can be paid now; draining one pool leaves the other way."""
    assert {name for name in _legal(_engine(_great_sage(), **held)) if name.startswith(GREAT_SAGE)} == legal


def test_the_ways_of_one_action_share_its_once_per_rest_use():
    """Great Sage is once per rest: using it in Stamina must not leave the Qi row usable."""
    bundle = _great_sage()
    rows = _costs(bundle)
    counters = {resource for name in (GREAT_SAGE, GREAT_SAGE_QI) for resource, _ in rows[name] if resource.startswith("resource:uses.")}
    assert len(counters) == 1  # one counter for both rows
    engine = _engine(bundle)
    _pay(engine, GREAT_SAGE)
    engine.state.actors["actor:factory.costs"].bonus_action_available = True  # not the bonus action: the rest use
    assert not {name for name in _legal(engine) if name.startswith(GREAT_SAGE)}


# -------------------------------------------------------------------------- a menu action, and ways that name Martial Focus


def _root_hewing(**kw):
    return _bundle(AXES, ["TAL_AXES_HEWING_STRIKE", ROOT_HEWING_KEY], AXE_KIT, **kw)


def test_every_option_of_a_menu_action_gets_the_ways():
    """Root-Hewing Passage ("2 CP, 2 Stamina, or 1 Martial Focus") has six options; each is paid any of the three ways."""
    expected = {}
    for option in ROOT_OPTIONS:
        expected[ROOT + option] = [("qi", 2)]
        expected[ROOT + option + " (2 Stamina)"] = [("stamina", 2)]
        expected[ROOT + option + " (Martial Focus)"] = [("martial_focus", 1)]
    assert _ways(_root_hewing(), ROOT) == expected


@pytest.mark.parametrize("primary,pool", [(QI_ONLY, "qi"), (STAMINA_ONLY, "stamina")], ids=["qi-only", "stamina-only"])
def test_a_single_pool_character_keeps_its_pool_and_the_martial_focus_way(primary, pool):
    """No row is offered in a pool the character lacks; Martial Focus is the one every character holds."""
    expected = {}
    for option in ROOT_OPTIONS:
        expected[ROOT + option] = [(pool, 2)]
        expected[ROOT + option + " (Martial Focus)"] = [("martial_focus", 1)]
    assert _ways(_root_hewing(primary=primary), ROOT) == expected


def test_a_way_that_pays_martial_focus_and_a_pool():
    """"2 CP, 2 Stamina, or expend Martial Focus and 1 CP": the third way is one row costing both."""
    bundle = _bundle(AXES, [SEVER_KEY], AXE_KIT)
    assert _ways(bundle, SEVER) == {SEVER: [("qi", 2)], SEVER + " (2 Stamina)": [("stamina", 2)],
                                    SEVER + " (Martial Focus + 1 Qi)": [("martial_focus", 1), ("qi", 1)]}
    assert _lost(_engine(bundle), SEVER + " (Martial Focus + 1 Qi)")[0] == {"martial_focus": 1, "qi": 1}
    assert _ways(_bundle(AXES, [SEVER_KEY], AXE_KIT, primary=STAMINA_ONLY), SEVER) == {
        SEVER: [("stamina", 2)], SEVER + " (Martial Focus + 1 Stamina)": [("martial_focus", 1), ("stamina", 1)]}


# ---------------------------------------------------------------------------------------------- reactions and the caps


@pytest.mark.parametrize("primary,pool", [(QI_ONLY, "qi"), (STAMINA_ONLY, "stamina"), (QI_STAMINA, "stamina")],
                         ids=["qi-only", "stamina-only", "both-pools"])
def test_a_reaction_pays_the_first_printed_way_the_character_can(primary, pool):
    """Laughing Theft of Timing is "5 Stamina or 5 CP".  A reaction compiles to one row (combat/typed_reactions.py is not changed):
    a Qi-only character pays 5 CP (it was 5 Stamina it could not pay), one with Stamina pays that, the first printed way."""
    bundle = _bundle(MONKEY, ["TAL_MONKEY_STYLE_LAUGHING_THEFT_OF_TIMING"], AXE_KIT, primary=primary)
    rows = [row for row in bundle["typed_reactions"] if row["feature_id"] == "TAL_MONKEY_STYLE_LAUGHING_THEFT_OF_TIMING"]
    assert len(rows) == 1
    assert [(cost["resource_id"].split(".")[-1], cost["amount"]) for cost in rows[0]["costs"] if cost["resource_id"].startswith("resource:core.")] == [(pool, 5)]


DAEMONIC = "tianxia.sphere.daemonic_cultivation"
DAEMONIC_TALENTS = ["TAL_DAEMONIC_CULTIVATION_DAEMONIC_AUGMENT", "TAL_DAEMONIC_CULTIVATION_DEMON_SEED", "TAL_DAEMONIC_CULTIVATION_HUNGER_REFINING_BREATH",
                    "TAL_DAEMONIC_CULTIVATION_PARASITE_MERIDIAN_NEEDLE", "TAL_DAEMONIC_CULTIVATION_WORLD_DEVOURING_MAW",
                    "TAL_DAEMONIC_CULTIVATION_BLACK_SUN_OVER_THE_DANTIAN"]


def _augmented(bundle):
    """The abilities Daemonic Augment has a variant on (a broad modifier: it lands on the strongest three)."""
    return {re.sub(r" \([^)]*\)$", "", name.split(" + ")[0]) for name in _costs(bundle) if " + Daemonic Augment" in name}


def test_a_second_pool_adds_ways_not_abilities_and_the_caps_count_abilities():
    """Daemonic Augment takes the three strongest abilities.  Demon Seed and Hunger-Refining Breath are "N CP or N Stamina", World-Devouring
    Maw "12 CP or 12 Devoured Essence": a way to pay is another row of the same ability, so counting rows would let the ways of one
    ability use up the three (and the eight variants each ability may carry).  Which abilities are augmented, and what is capped, must
    not depend on how many pools the character holds; and the augment lands on every way to pay the ability."""
    seen = {}
    for label, primary in (("qi", QI_ONLY), ("stamina", STAMINA_ONLY), ("both", QI_STAMINA)):
        bundle = _bundle(DAEMONIC, DAEMONIC_TALENTS, AXE_KIT, primary=primary, cl=15)
        assert all("capped" not in row for row in bundle["modifiers"]), label
        seen[label] = _augmented(bundle)
    assert seen["qi"] == seen["stamina"] == seen["both"] and len(seen["both"]) == 3
    both = _ways(_bundle(DAEMONIC, DAEMONIC_TALENTS, AXE_KIT, cl=15), "")
    assert both["Demon Seed"] == [("qi", 1)] and both["Demon Seed (1 Stamina)"] == [("stamina", 1)]
    assert both["Demon Seed + Daemonic Augment: Bonus Damage"] == [("qi", 2)]
    assert both["Demon Seed (1 Stamina) + Daemonic Augment: Bonus Damage"] == [("stamina", 2)]
    assert both["Hunger-Refining Breath (2 Stamina)"] == [("stamina", 2)]


def test_attacks_printed_cp_or_stamina_get_a_row_per_way():
    """Severing Fate ("15 CP or 15 Stamina") and Heaven-Cutting Crescent ("6 CP or 6 Stamina"), for each pool setup."""
    for primary, pool in ((QI_ONLY, "qi"), (STAMINA_ONLY, "stamina")):
        bundle = _bundle(SWORD, ["TAL_SWORD_SEVERING_FATE", "TAL_SWORD_HEAVEN_CUTTING_CRESCENT"], AXE_KIT, primary=primary, cl=15)
        assert {n: p for n, p in _ways(bundle, "") .items() if n.startswith(("Severing Fate", "Heaven-Cutting")) and " + " not in n} == {
            "Severing Fate": [(pool, 15)], "Heaven-Cutting Crescent": [(pool, 6)]}
    both = _bundle(SWORD, ["TAL_SWORD_SEVERING_FATE", "TAL_SWORD_HEAVEN_CUTTING_CRESCENT"], AXE_KIT, cl=15)
    assert {n: p for n, p in _ways(both, "").items() if n.startswith(("Severing Fate", "Heaven-Cutting")) and " + " not in n} == {
        "Severing Fate": [("qi", 15)], "Severing Fate (15 Stamina)": [("stamina", 15)],
        "Heaven-Cutting Crescent": [("qi", 6)], "Heaven-Cutting Crescent (6 Stamina)": [("stamina", 6)]}


# ------------------------------------------------------------------------------------------- the leftovers from K's modifiers


def _payments(bundle, prefix):
    """The set of ways (each a tuple of (pool, amount)) that the rows starting with ``prefix`` pay."""
    return {tuple(paid) for name, paid in _ways(bundle, prefix).items()}


BODY_RESONANCE = "Fu (Short Axe) attack + Body Resonance Strike"
BODY_RESONANCE_STAMINA = BODY_RESONANCE + " (1 STAMINA)"
BODY_RESONANCE_CP = BODY_RESONANCE + " (1 CP)"


@pytest.mark.parametrize("primary,ways", [
    (QI_STAMINA, {(("qi", 1),), (("stamina", 1),)}),
    (QI_ONLY, {(("qi", 1),)}),
    (STAMINA_ONLY, {(("stamina", 1),)}),
], ids=["both-pools", "qi-only", "stamina-only"])
def test_body_resonance_strike_is_paid_1_stamina_or_1_cp(primary, ways):
    """The printed melee-hit modifier pays one held pool per way, never a ranged Resonant Note."""
    bundle = _bundle(SOUND, ["TAL_SOUND_BODY_RESONANCE_STRIKE"], AXE_KIT, primary=primary)
    assert _payments(bundle, BODY_RESONANCE) == ways
    assert len(_ways(bundle, BODY_RESONANCE)) == len(ways)
    assert not _ways(bundle, "Resonant Note: Deafen + Body Resonance Strike")


def test_each_way_of_body_resonance_strike_spends_that_way_only():
    bundle = _bundle(SOUND, ["TAL_SOUND_BODY_RESONANCE_STRIKE"], AXE_KIT, dc=FAIL)
    assert _lost(_engine(bundle), BODY_RESONANCE_STAMINA)[0] == {"stamina": 1}
    assert _lost(_engine(bundle), BODY_RESONANCE_CP)[0] == {"qi": 1}
    assert {n for n in _legal(_engine(bundle, stamina=0)) if n.startswith(BODY_RESONANCE)} == {BODY_RESONANCE_CP}
    assert {n for n in _legal(_engine(bundle, qi=0)) if n.startswith(BODY_RESONANCE)} == {BODY_RESONANCE_STAMINA}


@pytest.mark.parametrize("primary,pool", [(QI_ONLY, "qi"), (STAMINA_ONLY, "stamina")])
@pytest.mark.parametrize("feature,label,amount", [
    ("TAL_SOUND_BODY_RESONANCE_STRIKE", "Body Resonance Strike", 1),
    ("TAL_SOUND_THUNDER_MERIDIAN_STRIKE", "Thunder-Meridian Strike", 2),
])
def test_single_pool_sound_weapon_strike_has_one_payable_way(primary, pool, feature, label, amount):
    bundle = _bundle(SOUND, [feature], AXE_KIT, primary=primary)
    prefix = "Fu (Short Axe) attack + " + label
    ways = _ways(bundle, prefix)
    # Thunder-Meridian has distinct printed outcomes, each with one payment.
    assert ways and all(paid == [(pool, amount)] for paid in ways.values())
    assert len(ways) == len({re.sub(r" \(\d+ (?:CP|STAMINA)\)$", "", name) for name in ways})
    name = next(iter(ways))
    assert _lost(_engine(bundle), name)[0] == {pool: amount}
    assert not {n for n in _legal(_engine(bundle, **{pool: 0})) if n.startswith(prefix)}


def test_nullifying_strike_is_paid_2_cp_or_2_stamina_on_every_option():
    """Every Void Pressure x Nullifying Strike option is paid in exactly one printed pool."""
    # Round 21 C4 adds the fourth printed failed-save option, Suppress Resistance.
    # Assert the exact option product so missing or duplicate options still fail.
    expected = {
        f"Void Needle: {pressure} + Nullifying Strike: {option}"
        for pressure in ("Empty Vitality", "Cost Lock", "Unsettle Invisibility")
        for option in ("No Reactions", "Speed -10", "Hollowed", "Suppress Resistance")
    }
    two = _ways(_bundle(VOID, ["TAL_VOID_NULLIFYING_STRIKE"], AXE_KIT), "Void Needle")
    rows = {name: paid for name, paid in two.items() if " + Nullifying Strike: " in name}
    assert len(rows) == 24
    groups = {}
    for name, paid in rows.items():
        groups.setdefault(re.sub(r" \(2 Stamina\)$", "", name), set()).add(tuple(paid))
    assert set(groups) == expected
    assert all(ways == {(("qi", 2),), (("stamina", 2),)} for ways in groups.values())
    for primary, pool in ((QI_ONLY, "qi"), (STAMINA_ONLY, "stamina")):
        one = _ways(_bundle(VOID, ["TAL_VOID_NULLIFYING_STRIKE"], AXE_KIT, primary=primary), "Void Needle")
        one = {name: paid for name, paid in one.items() if " + Nullifying Strike: " in name}
        assert set(one) == expected and all(paid == [(pool, 2)] for paid in one.values())


ARMY_BREAKING, PINNING = "Spear Thrust: Push Target + Army-Breaking Thrust: ", "Spear Thrust: Push Target + Pinning Strike: "


@pytest.mark.parametrize("primary,pool", [(QI_STAMINA, "qi"), (QI_ONLY, "qi"), (STAMINA_ONLY, "stamina")], ids=["both-pools", "qi-only", "stamina-only"])
def test_the_spear_modifiers_can_be_paid_with_martial_focus_instead_of_the_spear_resource(primary, pool):
    """"Cost: 2 Spear Resource or expend Martial Focus" (Army-Breaking Thrust; 1 for Pinning Strike): a Martial-Focus-only modifier that
    was paid in CP only, so a character out of CP could never use it.  Every option row now has a "(Martial Focus)" twin."""
    bundle = _bundle(SPEAR, ["TAL_SPEAR_ARMY_BREAKING_THRUST", "TAL_SPEAR_PINNING_STRIKE"], SPEAR_KIT, primary=primary)
    for prefix, amount in ((ARMY_BREAKING, 2), (PINNING, 1)):
        rows = _ways(bundle, prefix)
        focus = {name: paid for name, paid in rows.items() if name.endswith(" (Martial Focus)")}
        cp = {name: paid for name, paid in rows.items() if name not in focus}
        assert focus and len(focus) == len(cp)
        assert all(paid == [("martial_focus", 1)] for paid in focus.values())
        assert all(paid == [(pool, amount)] for paid in cp.values())
        assert {name[:-len(" (Martial Focus)")] for name in focus} == set(cp)


def test_each_way_of_pinning_strike_spends_that_way_only():
    bundle = _bundle(SPEAR, ["TAL_SPEAR_PINNING_STRIKE"], SPEAR_KIT, dc=FAIL)
    name = PINNING + "Reduce Speed"
    assert _lost(_engine(bundle), name)[0] == {"qi": 1}
    assert _lost(_engine(bundle), name + " (Martial Focus)")[0] == {"martial_focus": 1}
    assert {n for n in _legal(_engine(bundle, qi=0, stamina=0)) if n.startswith(name)} == {name + " (Martial Focus)"}
    assert {n for n in _legal(_engine(bundle, martial_focus=0)) if n.startswith(name)} == {name}
