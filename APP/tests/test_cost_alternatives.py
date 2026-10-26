"""Modifier cost alternatives (fix/cost-alternatives, from the sw-athletics report): a modifier printed "you may spend 2 CP,
2 Stamina, or expend Martial Focus and 1 CP/Stamina" (Hook the Giant's Knee) is paid ONE of those ways.  The modifier record
kept only two independent flags (``extra_cp``, ``martial_focus``) and the compiler charged both, so the printed choice cost
2 Stamina *and* Martial Focus.  The record now carries ``cost`` -- a list of alternatives, like a mechanic's own ``cost`` --
and the compiler builds one row per printed way to pay, so the engine's ordinary (conjunctive) payment applies to each row.

Attacks always hit (foe AC -50) and saves are forced with the sheet's technique DC (50: the foe fails, -40: it succeeds), so
the assertions read the branch the printed text names.
"""

import json
from functools import lru_cache
from pathlib import Path

import pytest

import combat.factory_compiler as factory_compiler
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from factory_authoring.typed_structure import modifier_cost_alternatives, modifier_from_text

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.costs"
AXES, SNIPER, SWORD = "tianxia.sphere.axes", "tianxia.sphere.sniper", "tianxia.sphere.sword"
AXE_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}]}}
SWORD_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.jian", "name": "Jian", "quantity": 1}]}}
BOW_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.gong_jian", "name": "Gong Jian", "quantity": 1}]}}
FAIL, PASS = 50, -40  # technique save DC that makes the foe fail / succeed every save
QI_STAMINA = {"name": "Qi", "maximum": 40, "definitions": [{"name": "Stamina", "max": 30}]}
QI_ONLY, STAMINA_ONLY = {"name": "Qi", "maximum": 40}, {"name": "Stamina", "maximum": 40}
HEWING, HOOK_KEY = "TAL_AXES_HEWING_STRIKE", "TAL_AXES_HOOK_THE_GIANT_S_KNEE"
STRIKE = "Fu (Short Axe) attack: Hewing Strike: "
HOOK = STRIKE + "Drive + Hook the Giant's Knee"
HOOK_ROWS = {  # display name -> costs, for a character with Qi and Stamina
    HOOK: [["resource:core.qi", 2]],
    HOOK + " (2 Stamina)": [["resource:core.stamina", 2]],
    HOOK + " (Martial Focus + 1 Qi)": [["resource:core.martial_focus", 1], ["resource:core.qi", 1]],
    HOOK + " (Martial Focus + 1 Stamina)": [["resource:core.martial_focus", 1], ["resource:core.stamina", 1]],
}
SNIPE = "Snipe Shot: Gong Jian (Bow and Arrow) + "


def _part(resource, amount):
    return {"resource": resource, "amount": amount} if resource == "martial_focus" else {"resource": resource, "amount": amount, "amount_formula": None}


def _three_ways(amount):
    return [[_part("cp", amount)], [_part("stamina", amount)], [_part("martial_focus", 1)]]


def _either(*ways):
    """One single-part alternative per (resource, amount): "N CP or N Stamina"."""
    return [[_part(resource, amount)] for resource, amount in ways]


HOOK_WAYS = [[_part("cp", 2)], [_part("stamina", 2)], [_part("martial_focus", 1), _part("cp", 1)], [_part("martial_focus", 1), _part("stamina", 1)]]
EITHER = [[_part("cp", 1)], [_part("martial_focus", 1)]]
ALTERNATIVES = {  # every modifier printed "spend N CP[, N Stamina] or expend Martial Focus[ and 1 CP/Stamina]"
    "TAL_AXES_CLEAVING_ARC": _three_ways(1), "TAL_AXES_DEEP_BITE": _three_ways(1), "TAL_AXES_HEADSMAN_S_RED_LINE": _three_ways(1),
    HOOK_KEY: HOOK_WAYS, "TAL_AXES_RENDING_HEW": _three_ways(1), "TAL_AXES_SHIELD_WALL_SPLITTER": _three_ways(1),
    "TAL_SNIPER_BREATH_HELD_SHOT": EITHER, "TAL_SNIPER_SUPPRESS_THE_FORMATION_LINE": EITHER,
    "TAL_SWORD_FATAL_STRIKE": _three_ways(8), "TAL_SWORD_MERIDIAN_CUTTING_STRIKE": _three_ways(3),
}
OR_BETWEEN_POOLS = {  # the modifiers with only one flag (extra_cp, or Martial Focus) whose text prints an "or" between the ways to pay
    "TAL_MONKEY_STYLE_CLOUD_SKIPPING_STEP": _either(("stamina", 1), ("cp", 1)),
    "TAL_MONKEY_STYLE_HEAVEN_BRIDGE_SWING": _either(("stamina", 2), ("cp", 2)),
    "TAL_SOUND_BODY_RESONANCE_STRIKE": _either(("stamina", 1), ("cp", 1)),
    "TAL_SOUND_THUNDER_MERIDIAN_STRIKE": _either(("stamina", 2), ("cp", 2)),
    "TAL_SPEAR_ARMY_BREAKING_THRUST": _either(("cp", 2), ("martial_focus", 1)),
    "TAL_SPEAR_PINNING_STRIKE": _either(("cp", 1), ("martial_focus", 1)),
    "TAL_SWORD_LIFE_SEVERING_SWORD": _either(("cp", 2), ("stamina", 2)),
    "TAL_VOID_HOLLOW_REBUKE": _either(("cp", 1), ("stamina", 1)),
    "TAL_VOID_NULLIFYING_STRIKE": _either(("cp", 2), ("stamina", 2)),
    "tianxia.talent.gravity.shared_weight": _either(("cp", 1), ("stamina", 1)),
    "tianxia.talent.gravity.ten_thousand_weight_body": _either(("cp", 5), ("stamina", 5)),
    "tianxia.talent.gravity.weight_borrowing_throw": _either(("cp", 1), ("stamina", 1)),
    "tianxia.talent.harvesting_gathering.bitter_spore_caution": _either(("cp", 1), ("stamina", 1)),
}
PAID_BOTH = {"TAL_QIWEAVING_COUNTERWEAVE", "TAL_SNIPER_FALLING_STAR_EXECUTION", "TAL_SNIPER_PHASIC_SHOT"}  # printed "X and expend Martial Focus"


# ------------------------------------------------------------------------------------------------------- harness


@lru_cache(maxsize=2)
def _load_mechanics(path):
    return json.loads(Path(path).read_bytes())["mechanics"]


def _mechanics():
    return _load_mechanics(str(factory_compiler.TYPED_AUTHORITY))


def _bundle(sphere, talents, kit, *, primary=QI_STAMINA, cl=10, dc=FAIL):
    bases = [key for key, mech in _mechanics().items() if mech.get("sphere_id") == sphere and mech.get("kind") == "base_ability"]
    sheet = {
        "identity": {"proficiency_bonus": 4, "cultivation_level": cl, "path": "Body Refining", "key_ability": "STR"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 16, "modifier": 3} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": dict(primary), "armor_class": {"base_value": 14}, "hit_points": {"maximum": 80},
            "speed": {"walking_ft": 30}, "technique_save_dc": dc, "technique_attack_bonus": 8,
        },
        "path_and_subpath": {"path_record_ids": ["tianxia.path.body_refining"]},
        "equipment": [kit],
        "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": list(talents), "automatic_sphere_component_record_ids": bases},
    }
    return compile_character(sheet, actor_id=ME)


def _hook_bundle(**kw):
    return _bundle(AXES, [HEWING, HOOK_KEY], AXE_KIT, **kw)


def _costs(bundle):
    """display name -> costs of every row."""
    return {row["display_name"]: [list(cost) for cost in row["costs"]] for row in bundle["action_catalog"]}


def _engine(bundle, *, foe_at=(4, 6), foe_large=False, **resources):
    """A turn with the foe next to us, its AC out of reach; ``resources`` overrides what the actor holds (qi=0, martial_focus=1 ...)."""
    engine = Gate4ControllerEngine(ROOT, match_seed="COSTS", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    engine.state.actors[AN].armor_class = -50
    if foe_large:
        # Hook the Giant's Knee only applies to a creature larger than its user.
        engine.actor_footprints[AN] = engine._footprint(AN).model_copy(update={
            "width_cells": 2, "height_cells": 2, "occupied_relative_cells": (
                Position(x=0, y=0), Position(x=1, y=0), Position(x=0, y=1), Position(x=1, y=1))})
    me = engine.state.actors[ME]
    me.action_available, me.bonus_action_available, me.reaction_available = True, True, True
    for suffix, value in resources.items():
        _set(me, suffix, value)
    return engine


def _set(actor, suffix, value):
    actor.resources[next(key for key in actor.resources if key.endswith("." + suffix))] = value


def _legal(engine):
    return {c.display_name for c in engine.legal_candidates()}


def _pay(engine, name):
    """Use ``name``; returns (what the actor lost, the resource-spent events, the foe's modifiers)."""
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    matches = [c for c in engine.legal_candidates() if c.display_name == name]
    assert matches, f"{name!r} is not a legal action; legal: {sorted(_legal(engine))}"
    candidate, before, mark = matches[0], dict(me.resources), len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids or (AN,),
                                       destination=candidate.destination))
    spent = {key.split(".")[-1]: before[key] - value for key, value in me.resources.items() if before[key] != value}
    events = [e for e in engine.events[mark:] if e.event_type == "RESOURCE_SPENT"]
    return spent, events, [(m.target_field, m.value) for m in foe.modifiers.values()]


# ------------------------------------------------------------------------------------ reading the printed alternatives


def test_the_printed_or_is_read_as_alternatives():
    """"spend 2 CP, 2 Stamina, or expend Martial Focus and 1 CP/Stamina": four ways to pay, one of which is paid."""
    hook = {"extra_cp": 2, "martial_focus": True}
    assert modifier_cost_alternatives("you may spend 2 CP, 2 Stamina, or expend Martial Focus and 1 CP/Stamina.", hook) == HOOK_WAYS
    assert modifier_cost_alternatives("you may spend 1 CP or expend Martial Focus to attempt a deeper suppression.",
                                      {"extra_cp": 1, "martial_focus": True}) == EITHER
    assert modifier_cost_alternatives("Cost: 3 CP, 3 Stamina, or expend Martial Focus", {"extra_cp": 3, "martial_focus": True}) == _three_ways(3)


def test_a_printed_and_stays_both_and_a_disagreeing_amount_is_left_alone():
    """Phasic Shot ("expend Martial Focus and spend 2 CP") really costs both.  A text whose CP amount is not the modifier's, or a
    modifier with neither flag, or one whose flag does not fit the text's "or", is not rewritten.  (A Martial-Focus-only modifier
    whose text prints a CP way is read now: test_a_martial_focus_only_or_and_an_extra_cp_only_or_are_read.)"""
    both = {"extra_cp": 2, "martial_focus": True}
    assert modifier_cost_alternatives("When making a Snipe Shot through an Aimed Line, expend Martial Focus and spend 2 CP.", both) is None
    assert modifier_cost_alternatives("Cost: 1 CP and expend Martial Focus", {"extra_cp": 1, "martial_focus": True}) is None
    assert modifier_cost_alternatives("you may spend 3 CP or expend Martial Focus", both) is None  # 3 is not this modifier's 2
    assert modifier_cost_alternatives("you may spend 2 CP or expend Martial Focus", {"extra_cp": 2}) is None  # no Martial Focus flag to pay it with
    assert modifier_cost_alternatives("you may spend 2 CP or expend Martial Focus", None) is None
    assert modifier_cost_alternatives("", both) is None


def test_a_martial_focus_only_or_and_an_extra_cp_only_or_are_read():
    """The two shapes the flags alone could not say.  A Martial-Focus-only modifier printed "Cost: 2 Spear Resource or expend Martial
    Focus" (Army-Breaking Thrust, Pinning Strike) is paid with the Spear resource -- a CP, as the reviewed authority types it -- or with
    Martial Focus.  An extra-CP-only modifier printed "spend 1 Stamina or 1 CP" (Body Resonance Strike, Nullifying Strike, ...) is paid
    with either pool.  The first printed way stays first; a text this reader cannot place is left as it was."""
    focus = {"martial_focus": True}
    assert modifier_cost_alternatives("Cost: 2 Spear Resource or expend Martial Focus", focus) == _either(("cp", 2), ("martial_focus", 1))
    assert modifier_cost_alternatives("Cost: 1 Spear Resource or expend Martial Focus", focus) == _either(("cp", 1), ("martial_focus", 1))
    assert modifier_cost_alternatives("you may spend 2 CP or expend Martial Focus", focus) == _either(("cp", 2), ("martial_focus", 1))
    assert modifier_cost_alternatives("Cost: 2 CP or 2 Stamina", {"extra_cp": 2}) == _either(("cp", 2), ("stamina", 2))
    assert modifier_cost_alternatives("you may spend 1 Stamina or 1 CP to release a close vibration", {"extra_cp": 1}) == _either(("stamina", 1), ("cp", 1))
    assert modifier_cost_alternatives("Cost: +1 Stamina or +1 CP when activating Capering Footwork", {"extra_cp": 1}) == _either(("stamina", 1), ("cp", 1))
    assert modifier_cost_alternatives("you may spend 1 CP or Stamina to apply the same mode", {"extra_cp": 1}) == _either(("cp", 1), ("stamina", 1))
    assert modifier_cost_alternatives("you may spend 5 CP or Stamina at the start of your turn", {"extra_cp": 5}) == _either(("cp", 5), ("stamina", 5))
    # left alone: no "or", an "and", an amount that is not the modifier's, a further way naming a pool it does not know, no flag
    assert modifier_cost_alternatives("Cost: 2 Spear Resource", focus) is None
    assert modifier_cost_alternatives("you may spend 2 CP and 2 Stamina", {"extra_cp": 2}) is None
    assert modifier_cost_alternatives("you may spend 2 CP", {"extra_cp": 2}) is None
    assert modifier_cost_alternatives("Cost: 2 CP or 2 Stamina", {"extra_cp": 1}) is None
    assert modifier_cost_alternatives("Cost: 1 CP, 1 Stamina, or 1 Devoured Essence", {"extra_cp": 1}) is None
    assert modifier_cost_alternatives("you may spend 2 CP or 2 Stamina", {}) is None


def test_the_parser_attaches_the_alternatives_only_when_the_text_prints_an_or():
    hook = modifier_from_text("Hook the Giant's Knee", "When you hit a creature larger than you with Hewing Strike, you may spend 2 CP, "
                              "2 Stamina, or expend Martial Focus and 1 CP/Stamina.\nThe target makes a Strength saving throw.",
                              "Hewing Strike", "When you hit a creature larger than you with Hewing Strike", [])
    assert (hook["extra_cp"], hook["martial_focus"], hook["cost"]) == (2, True, HOOK_WAYS)
    phasic = modifier_from_text("Phasic Shot", "When making a Snipe Shot through an Aimed Line, expend Martial Focus and spend 2 CP.",
                                "Snipe Shot", "When making a Snipe Shot", [])
    assert (phasic["extra_cp"], phasic["martial_focus"]) == (2, True) and "cost" not in phasic


def test_every_modifier_paid_with_an_or_carries_its_alternatives_in_the_authority():
    """Thirteen modifiers carry both flags.  Ten print an "or" (their ``cost`` lists the ways); three print an "and" (Counterweave,
    Falling Star Execution, Phasic Shot) and keep paying both.  A fourteenth both-flag modifier that is in neither list is a new
    printed shape: teach modifier_cost_alternatives to read it (or add it to the "and" list if it is one)."""
    mechanics = _mechanics()
    both_flags = {key for key, mech in mechanics.items() if (mech.get("modifier") or {}).get("extra_cp") and mech["modifier"].get("martial_focus")}
    assert both_flags == set(ALTERNATIVES) | PAID_BOTH
    for key, ways in ALTERNATIVES.items():
        assert mechanics[key]["modifier"]["cost"] == ways, key
    for key in PAID_BOTH:
        assert not mechanics[key]["modifier"].get("cost"), key


def test_the_modifiers_that_print_an_or_between_pools_carry_it_in_the_authority():
    """Thirteen modifiers with a single flag print "N Stamina or N CP" / "N Spear Resource or expend Martial Focus".  The authority is
    built from the printed text (tools/build_typed_mechanics_authority.py), so no modifier whose text this reader understands may be
    left without ``cost``: rebuild the authority when a new one shows up here."""
    mechanics = _mechanics()
    for key, ways in OR_BETWEEN_POOLS.items():
        assert mechanics[key]["modifier"]["cost"] == ways, key
    texts = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_bytes())
    unread = [key for key, mech in mechanics.items()
              if mech.get("modifier") and not mech["modifier"].get("cost") and modifier_cost_alternatives(texts.get(key) or "", mech["modifier"])]
    assert not unread, f"rebuild the authority: {unread}"


def test_hollow_path_step_reaction_keeps_both_printed_payment_ways():
    # Round 21 C4 implements the printed miss-triggered reaction, replacing
    # the old attack modifier. Keep checking its CP-or-Stamina alternatives.
    row = _mechanics()["TAL_VOID_HOLLOW_PATH_STEP"]
    assert not row.get("modifier")
    assert row["cost"] == _either(("cp", 2), ("stamina", 2))
    assert any(effect["type"] == "void_path_step" for effect in row["effects"])


def test_a_modifier_that_states_its_own_cost_agrees_with_it():
    """Fatal Strike and Meridian-Cutting Strike print "Cost: N CP, N Stamina, or expend Martial Focus" as the talent's own cost."""
    for key in ("TAL_SWORD_FATAL_STRIKE", "TAL_SWORD_MERIDIAN_CUTTING_STRIKE"):
        assert _mechanics()[key]["modifier"]["cost"] == _mechanics()[key]["cost"], key


# ------------------------------------------------------------------------------------------- what the compiler builds


def test_hook_the_giants_knee_is_one_row_per_printed_way_to_pay():
    """The row used to cost Qi 2 (or Stamina 2) *and* Martial Focus."""
    costs = _costs(_hook_bundle())
    assert {name: costs[name] for name in costs if name.startswith(HOOK)} == HOOK_ROWS


@pytest.mark.parametrize("primary,ways", [
    (QI_ONLY, {HOOK: [["resource:core.qi", 2]], HOOK + " (Martial Focus + 1 Qi)": [["resource:core.martial_focus", 1], ["resource:core.qi", 1]]}),
    (STAMINA_ONLY, {HOOK: [["resource:core.stamina", 2]],
                    HOOK + " (Martial Focus + 1 Stamina)": [["resource:core.martial_focus", 1], ["resource:core.stamina", 1]]}),
], ids=["qi-only", "stamina-only"])
def test_a_character_without_one_of_the_pools_gets_only_the_ways_it_can_pay(primary, ways):
    """"CP" is whichever pool the character has; a way to pay in a pool it lacks is not offered."""
    costs = _costs(_hook_bundle(primary=primary))
    assert {name: costs[name] for name in costs if name.startswith(HOOK)} == ways


def test_the_alternatives_multiply_rows_not_the_choices_the_caps_count():
    """Six Axes modifiers on one Qi + Stamina character: every one is applied, none reports being capped, and Hook's four ways are
    four rows on each Hewing Strike option (the caps count a modifier's choices, not the rows a choice pays in)."""
    keys = ["TAL_AXES_CLEAVING_ARC", "TAL_AXES_DEEP_BITE", "TAL_AXES_HEADSMAN_S_RED_LINE", HOOK_KEY, "TAL_AXES_RENDING_HEW",
            "TAL_AXES_SHIELD_WALL_SPLITTER"]
    bundle = _bundle(AXES, [HEWING, *keys], AXE_KIT)
    assert bundle["modifiers"] and all(row["status"] == "applied" and "capped" not in row for row in bundle["modifiers"])
    hook_rows = [name for name in _costs(bundle) if " + Hook the Giant's Knee" in name]
    assert len(hook_rows) == 5 * 4  # the five Hewing Strike options, four ways each
    assert len({name.split(" + Hook")[0] for name in hook_rows}) == 5


def test_sniper_and_sword_modifiers_get_their_rows_too():
    sniper = _costs(_bundle(SNIPER, ["TAL_SNIPER_BREATH_HELD_SHOT"], BOW_KIT))
    assert sniper[SNIPE + "Breath-Held Shot"] == [["resource:core.qi", 1]]
    assert sniper[SNIPE + "Breath-Held Shot (Martial Focus)"] == [["resource:core.martial_focus", 1]]
    talents = ["TAL_SWORD_FATAL_STRIKE", "TAL_SWORD_MERIDIAN_CUTTING_STRIKE"]
    # Sword in Hand is "Replace one attack with one Sword weapon attack" (its printed range is "Sword reach"): it is made with a
    # Sword weapon, so it is on the menu under that weapon's name and only for a character that carries one (review sw-spirit_companions).
    assert not [name for name in _costs(_bundle(SWORD, talents, AXE_KIT, cl=15)) if "Sword in Hand" in name]
    sword = _costs(_bundle(SWORD, talents, SWORD_KIT, cl=15))
    # Both talents are limited to once per scene, so each way to pay also spends the one use per fight (fix/use-limits).
    fatal, meridian = ["resource:uses.TAL_SWORD_FATAL_STRIKE", 1], ["resource:uses.TAL_SWORD_MERIDIAN_CUTTING_STRIKE", 1]
    for base in ("Jian (Straight Sword) attack: Sword in Hand + ", "Sword Beyond Hand + "):
        assert sword[base + "Fatal Strike"] == [["resource:core.qi", 8], fatal]
        assert sword[base + "Fatal Strike (8 Stamina)"] == [["resource:core.stamina", 8], fatal]
        assert sword[base + "Fatal Strike (Martial Focus)"] == [["resource:core.martial_focus", 1], fatal]
        assert [c for c in sword[base + "Meridian-Cutting Strike"] if c != meridian] == [["resource:core.qi", 3]]
        assert [c for c in sword[base + "Meridian-Cutting Strike (3 Stamina)"] if c != meridian] == [["resource:core.stamina", 3]]
        assert [c for c in sword[base + "Meridian-Cutting Strike (Martial Focus)"] if c != meridian] == [["resource:core.martial_focus", 1]]


def test_a_modifier_printed_with_and_keeps_paying_both():
    """Phasic Shot: "expend Martial Focus and spend 2 CP" is one row costing both, and it is not legal without the Martial Focus."""
    bundle = _bundle(SNIPER, ["TAL_SNIPER_PHASIC_SHOT"], BOW_KIT)
    phasic = {name: costs for name, costs in _costs(bundle).items() if name.endswith("Phasic Shot")}
    assert phasic == {SNIPE + "Phasic Shot": [["resource:core.qi", 2], ["resource:core.martial_focus", 1]]}
    assert SNIPE + "Phasic Shot" in _legal(_engine(bundle))
    assert SNIPE + "Phasic Shot" not in _legal(_engine(bundle, martial_focus=0))


# ------------------------------------------------------------------------------------------------ paying in the engine


@pytest.mark.parametrize("name,spent", [
    (HOOK, {"qi": 2}),
    (HOOK + " (2 Stamina)", {"stamina": 2}),
    (HOOK + " (Martial Focus + 1 Qi)", {"qi": 1, "martial_focus": 1}),
    (HOOK + " (Martial Focus + 1 Stamina)", {"stamina": 1, "martial_focus": 1}),
], ids=["2-qi", "2-stamina", "focus-and-qi", "focus-and-stamina"])
def test_each_way_to_pay_hook_the_giants_knee_spends_that_way_only(name, spent):
    """Whichever way is used, the actor loses exactly that and the effect lands: the Failed Save halves the target's movement mode."""
    engine = _engine(_hook_bundle(dc=FAIL), foe_large=True)
    lost, events, foe_modifiers = _pay(engine, name)
    assert lost == spent
    assert len(events) == len(spent)  # one RESOURCE_SPENT per part of the way to pay
    assert ("speed_halved", 1) in foe_modifiers


def test_a_successful_save_takes_the_same_payment():
    engine = _engine(_hook_bundle(dc=PASS), foe_large=True)
    lost, _, foe_modifiers = _pay(engine, HOOK + " (2 Stamina)")
    assert lost == {"stamina": 2} and ("speed_ft", -10) in foe_modifiers and ("speed_halved", 1) not in foe_modifiers


@pytest.mark.parametrize("held,legal", [
    ({"stamina": 1}, {HOOK, HOOK + " (Martial Focus + 1 Qi)", HOOK + " (Martial Focus + 1 Stamina)"}),
    ({"martial_focus": 0}, {HOOK, HOOK + " (2 Stamina)"}),
    ({"qi": 1, "stamina": 1}, {HOOK + " (Martial Focus + 1 Qi)", HOOK + " (Martial Focus + 1 Stamina)"}),
    ({"qi": 0, "stamina": 0}, set()),
    ({"qi": 1, "stamina": 0}, {HOOK + " (Martial Focus + 1 Qi)"}),
    ({"qi": 0, "stamina": 1, "martial_focus": 0}, set()),
], ids=["one-stamina", "no-focus", "one-of-each", "nothing-but-focus", "one-qi", "one-stamina-no-focus"])
def test_only_the_ways_the_actor_can_afford_are_legal(held, legal):
    """The AI (and a player's menu) only ever sees the ways that can be paid now."""
    engine = _engine(_hook_bundle(), **held)
    assert {name for name in _legal(engine) if name.startswith(HOOK)} == legal


@pytest.mark.parametrize("name,spent", [
    (SNIPE + "Breath-Held Shot", {"qi": 1}),
    (SNIPE + "Breath-Held Shot (Martial Focus)", {"martial_focus": 1}),
], ids=["1-qi", "focus"])
def test_breath_held_shot_is_paid_with_cp_or_with_martial_focus(name, spent):
    """"you may spend 1 CP or expend Martial Focus": it charged Qi 1 *and* Martial Focus."""
    # What was paid, not what is missing afterwards: a missed Breath-Held Shot gives the payment back (riders lane 4).
    _, events, _ = _pay(_engine(_bundle(SNIPER, ["TAL_SNIPER_BREATH_HELD_SHOT"], BOW_KIT)), name)
    assert {e.payload["resource_id"].split(".")[-1]: e.payload["amount"] for e in events} == spent
