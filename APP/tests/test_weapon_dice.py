"""Printed "weapon damage die" (fix/cost-alternatives, from the sw-athletics report): an ability that rolls "the normal weapon
damage die of each weapon in your Qualifying Pair" (Cyclone Cut), "one Bow weapon damage die" (Sun-Chasing Line), "two Draw
Weapon damage dice" (One Breath, Three Horizons) or "one weapon damage die" (Crescent Reaping Circle) carried its damage as
a parser stub or without the weapon's die, so it rolled nothing (or an untyped 1d4).  The authority now types each printed die
``dice.weapon`` with the printed count and a ``dice.weapon_group`` naming whose die it is; combat/factory_compiler._weapon_dice
fills in that weapon's die size.

Cyclone Cut is a live action, so it is run through the engine (attacks always hit and the technique DC forces the save:
50 fails it, -40 passes it).  The three subpath features are typed "passive" and compile to no action yet, so the compiler
step is run directly on a row made from their typed effects.
"""

import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest

import combat.factory_compiler as factory_compiler
from combat.factory_compiler import _walk, _weapon_dice, compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind
from combat.gate4_engine import Gate4ControllerEngine

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.dice"
DUAL = "tianxia.sphere.dual_wielding"
CYCLONE = "TAL_DUAL_WIELDING_CYCLONE_CUT"
SUN_CHASING = "tianxia.subpath.body.sun_piercing_bow_body.feature.sun_chasing_line"
ONE_BREATH = "tianxia.subpath.body.still_water_draw_body.feature.one_breath_three_horizons"
CRESCENT = "tianxia.subpath.body.white_heron_crescent_body.feature.crescent_reaping_circle"
FAIL, PASS = 50, -40  # technique save DC that makes the foe fail / succeed every save


# ------------------------------------------------------------------------------------------------------- harness


@lru_cache(maxsize=2)
def _load_mechanics(path):
    return json.loads(Path(path).read_bytes())["mechanics"]


def _mechanics():
    return _load_mechanics(str(factory_compiler.TYPED_AUTHORITY))


def _weapon_dice_of(key):
    """[(count, group, formula)] of the weapon-die damage effects of a mechanic, wherever they nest."""
    return [(effect["dice"]["count"], effect["dice"].get("weapon_group"), effect.get("formula"))
            for effect in _walk(_mechanics()[key]["effects"]) if isinstance(effect.get("dice"), dict) and effect["dice"].get("weapon")]


def _kit(*item_ids):
    return {"starting_kit": {"items": [{"item_id": f"tianxia.mortal.weapon.{item}", "name": item, "quantity": 1} for item in item_ids]}}


def _bundle(items, *, dc):
    bases = [key for key, mech in _mechanics().items() if mech.get("sphere_id") == DUAL and mech.get("kind") == "base_ability"]
    sheet = {
        "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Body Refining", "key_ability": "STR"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 16, "modifier": 3} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Stamina", "maximum": 60}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 80},
            "speed": {"walking_ft": 30}, "technique_save_dc": dc, "technique_attack_bonus": 8,
        },
        "path_and_subpath": {"path_record_ids": ["tianxia.path.body_refining"]},
        "equipment": [_kit(*items)],
        "spheres_and_talents": {"sphere_record_ids": [DUAL], "learned_talent_record_ids": [CYCLONE], "automatic_sphere_component_record_ids": bases},
    }
    return compile_character(sheet, actor_id=ME)


def _cyclone_cut(items, *, dc):
    """Use Cyclone Cut on an adjacent foe: (the damage rolls, the damage types committed, hit points the foe lost, what the actor spent)."""
    bundle = _bundle(items, dc=dc)
    engine = Gate4ControllerEngine(ROOT, match_seed="DICE", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    me.action_available, me.bonus_action_available, me.reaction_available = True, True, True
    matches = [c for c in engine.legal_candidates() if c.display_name == "Cyclone Cut"]
    assert matches, f"Cyclone Cut is not a legal action; legal: {sorted(c.display_name for c in engine.legal_candidates())}"
    candidate, hp, before, mark = matches[0], foe.current_hp, dict(me.resources), len(engine.events)
    engine.execute_intent(ActionIntent(intent_id="i-cyclone", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids or (AN,),
                                       destination=candidate.destination))
    events = engine.events[mark:]
    rolled = [e.payload for e in events if e.event_type == "DAMAGE_ROLLED"]
    committed = [e.payload["damage_type"] for e in events if e.event_type == "DAMAGE_COMMITTED"]
    spent = {key.split(".")[-1]: before[key] - value for key, value in me.resources.items() if before[key] != value}
    return rolled, committed, hp - foe.current_hp, spent


def _weapon(item, sides, *, count=1, damage_type="SLASHING", melee=True, ranged=False, thrown=False, pairable=False):
    """A carried weapon: its ``weapon_kinds`` entry and its attack row, as the compiler builds them."""
    action_id = f"action:typed.dice.weapon.{item}"
    kind = {"action_id": action_id, "name": item, "item_id": f"tianxia.mortal.weapon.{item}", "melee": melee, "ranged": ranged,
            "thrown": thrown, "proficient": True, "pairable": pairable}
    row = ActionDefinition(source_definition_id=action_id, display_name=f"{item} attack", owner_id=ME, economy=EconomyKind.ACTION,
                           resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5,
                           parameters={"typed": {"effects": [], "weapon": {"damage": {"count": count, "sides": sides, "modifier": 3},
                                                                           "damage_type": damage_type, "damage_types": [damage_type]}}})
    return kind, row


def _compiled(key, *weapons):
    """The ability of ``key`` after _weapon_dice, for a character carrying these weapons: (its weapon dice as (count, sides), the row)."""
    feature = ActionDefinition(source_definition_id="action:typed.dice.feature", display_name=key.rsplit(".", 1)[-1], owner_id=ME,
                               economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5,
                               parameters={"typed": {"effects": copy.deepcopy(_mechanics()[key]["effects"]), "numbers": {"cl": 14, "pb": 4, "key_mod": 3},
                                                     "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0})
    kinds = [kind for kind, _ in weapons]
    row = _weapon_dice([feature, *(weapon for _, weapon in weapons)], kinds, _mechanics())[0]
    dice = [(effect["dice"]["count"], effect["dice"]["sides"]) for effect in _walk(row.parameters["typed"]["effects"])
            if isinstance(effect.get("dice"), dict) and effect["dice"].get("weapon")]
    return dice, row


# ----------------------------------------------------------------------------------------- what the authority types


def test_the_printed_weapon_dice_are_typed_with_their_count_and_whose_die_they_are():
    """Each mechanic rolls the printed number of the named weapon's die, the Constitution modifier once, beside its own dice."""
    assert _weapon_dice_of(CYCLONE) == [(2, "pair", "none")]  # each weapon of the pair once, added together
    assert _weapon_dice_of(SUN_CHASING) == [(1, "bow", "none")]  # the 4d8 effect carries the Constitution modifier
    assert _weapon_dice_of(ONE_BREATH) == [(2, "melee", "none")]  # two Draw Weapon dice
    assert _weapon_dice_of(CRESCENT) == [(1, "polearm", "key_ability_modifier")]  # this effect carries the Constitution modifier
    for key in (CYCLONE, SUN_CHASING, ONE_BREATH, CRESCENT):
        assert _mechanics()[key]["typing_status"] == "reviewed_final", key


def test_every_weapon_group_the_authority_names_is_one_the_compiler_knows():
    """A misspelt ``weapon_group`` would silently leave the authority's placeholder d4 in place."""
    known = set(factory_compiler._weapon_rules()["proficiency"]["groups"]) | {"melee", "pair"}
    named = {effect["dice"]["weapon_group"] for mechanic in _mechanics().values() for effect in _walk(mechanic.get("effects") or [])
             if isinstance(effect.get("dice"), dict) and effect["dice"].get("weapon_group")}
    assert {"pair", "bow", "melee", "polearm"} <= named <= known


# ---------------------------------------------------------------------------------------------------------- Cyclone Cut


@pytest.mark.parametrize("items,expression", [
    (("duan_jian", "fu"), ["1d6+0", "1d6+0"]),  # two d6 weapons
    (("duan_jian", "bi_shou"), ["1d6+0", "1d4+0"]),  # each ordinary printed die
    (("hu_die_dao",), ["1d6+0", "1d6+0"]),  # one Paired weapon is its own twin
    (("emei_ci",), ["1d4+0", "1d4+0"]),
], ids=["jian+fu", "jian+bi-shou", "hu-die-dao", "emei-ci"])
def test_cyclone_cut_rolls_the_die_of_each_weapon_in_the_pair(items, expression):
    """"Roll the normal weapon damage die of each weapon in your Qualifying Pair once and add the results together. Failed Save:
    The creature takes Bludgeoning damage equal to the total."  It rolled an untyped 1d4 (the placeholder die of a parser stub)."""
    rolled, committed, lost, spent = _cyclone_cut(items, dc=FAIL)
    assert sorted(roll["expression"] for roll in rolled) == sorted(expression)
    assert rolled[0]["modifier"] == 0  # "Cyclone Cut does not add your ability modifier"
    assert committed == ["BLUDGEONING"] and spent == {"martial_focus": 1}
    assert lost == sum(roll["total"] for roll in rolled)


def test_cyclone_cut_deals_half_on_a_successful_save():
    rolled, committed, lost, _ = _cyclone_cut(("duan_jian", "fu"), dc=PASS)
    assert [roll["expression"] for roll in rolled] == ["1d6+0", "1d6+0"] and committed == ["BLUDGEONING"]
    assert lost == sum(roll["total"] for roll in rolled) // 2


# ------------------------------------------------------------------------------------- the compiler step, per feature


def test_sun_chasing_line_rolls_the_bows_die_not_the_biggest_thrown_die():
    """"one Bow weapon damage die": the Gong Jian's d8, though a thrown javelin carried beside it is a d12."""
    dice, row = _compiled(SUN_CHASING, _weapon("gong_jian", 8, damage_type="PIERCING", melee=False, ranged=True),
                          _weapon("javelin", 12, damage_type="PIERCING", melee=True, ranged=True, thrown=True))
    assert dice == [(1, 8)]
    assert row.parameters["expected_damage"] > 0  # the combat AI sees the bigger die (the placeholder d4 was counted before)


def test_crescent_reaping_circle_rolls_the_polearms_die():
    """"one weapon damage die" of "the integrated Polearm": the Guandao's d10 though a Jian carried beside it is a d12."""
    dice, _ = _compiled(CRESCENT, _weapon("jian", 12), _weapon("guandao_yanyuedao", 10))
    assert dice == [(1, 10)]


def test_one_breath_rolls_two_dice_of_the_biggest_melee_weapon():
    """"two Draw Weapon damage dice": the sheet does not record which weapon is drawn, so the biggest melee weapon carried."""
    dice, _ = _compiled(ONE_BREATH, _weapon("jian", 6), _weapon("guandao_yanyuedao", 10), _weapon("gong_jian", 12, melee=False, ranged=True))
    assert dice == [(2, 10)]  # the bow, a ranged-only weapon, is not a Draw Weapon


def test_legacy_compiler_pair_placeholder_is_superseded_by_the_readied_pair_roll():
    """The generic compile estimate stays conservative; the tagged native cache gets exact live dice at execution."""
    dice, _ = _compiled(CYCLONE, _weapon("jian", 8, pairable=True), _weapon("duan_jian", 6, pairable=True), _weapon("bi_shou", 4, pairable=True),
                        _weapon("da_dao", 12))
    assert dice == [(2, 6)]
    equal, _ = _compiled(CYCLONE, _weapon("jian", 6, pairable=True), _weapon("duan_jian", 6, pairable=True))
    assert equal == [(2, 6)]


def test_no_weapon_of_the_named_group_leaves_the_authoritys_die_and_the_scoring_alone():
    dice, row = _compiled(SUN_CHASING, _weapon("jian", 8))  # no bow
    assert dice == [(1, 4)] and row.parameters["expected_damage"] == 0
    dice, _ = _compiled(CRESCENT)  # no weapon at all
    assert dice == [(1, 4)]
