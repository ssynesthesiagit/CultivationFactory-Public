"""The four armour AC defects from AUDIT4, at the level each one showed.

Each test drives ``compile_character`` — the real compilation the sheet and the
fight both read — so it fails if the number regresses, not just the helper.

1. The printed Dexterity cap was never applied, because the formula regex wanted
   "(max 2)" and every record prints "(max +2)".
2. A Shield carried as an ordinary starting-kit item gave no +2 AC at all,
   although the compiler recorded a +2 passive for it, so Break Guard and
   Sacrificial Shield pushed AC below the true value.
3. The printed Strength requirement was recorded and never enforced.  In D&D
   5.5e that costs Speed, not AC.
4. max(base, armour) let a higher unarmored calculation beat worn armour, where
   alternate AC calculations replace rather than stack.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from combat.factory_compiler import compile_character

_spec = importlib.util.spec_from_file_location("_mmx14_athletics", Path(__file__).with_name("test_review_sw-athletics.py"))
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)

SHIELD = "tianxia.mortal.armor.shield"
# 12 + Dex modifier (max +2): 2024 medium armour caps Dexterity at +2.
MEDIUM = "tianxia.mortal.armor.beast_hide_harness"
# 11 + Dex modifier: 2024 light armour takes the whole Dexterity modifier.
LIGHT = "tianxia.mortal.armor.lacquered_leather"
# AC 18, "Str 15": the Plate that made the audit's third row.
HEAVY = "tianxia.mortal.armor.imperial_plate_battle_dress"
AXE = "tianxia.mortal.weapon.fu"


def _kit(*item_ids):
    return {"items": [{"item_id": item_id, "name": item_id.rsplit(".", 1)[-1], "quantity": 1} for item_id in item_ids]}


def _sheet(kit, *, dex=20, strength=16, base_ac=14, speed=30):
    """A real sheet: the compiler reads DEX/STR scores and the base AC from here."""
    return {
        "proficiencies": {"armor": ["Shield"]}, "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Body Refining", "key_ability": "STR"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": ability, "score": score, "modifier": (score - 10) // 2}
                          for ability, score in (("STR", strength), ("DEX", dex), ("CON", 16), ("INT", 12), ("WIS", 14), ("CHA", 10))],
            "primary_resource": {"name": "Stamina", "maximum": 60}, "armor_class": {"base_value": base_ac},
            "hit_points": {"maximum": 80}, "speed": {"walking_ft": speed},
            "technique_save_dc": 16, "technique_attack_bonus": 8,
        },
        "path_and_subpath": {"path_record_ids": ["tianxia.path.body_refining"]},
        "equipment": [{"starting_kit": kit}],
        "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": [], "automatic_sphere_component_record_ids": []},
    }


def _ac(kit, **kwargs):
    return compile_character(_sheet(kit, **kwargs), actor_id="actor:factory.hero")["actor_template"]["armor_class"]


def _speed(kit, **kwargs):
    return compile_character(_sheet(kit, **kwargs), actor_id="actor:factory.hero")["actor_template"]["speed_ft"]


# --- 1. the printed Dexterity cap ------------------------------------------------

def test_medium_armor_caps_dexterity_at_plus_two():
    """Beast-Hide Harness is "12 + Dex modifier (max +2)": DEX 20 is +5, and the cap holds it at +2.

    ``base_ac=10`` is a plain unarmored 10, well below every number here, so the armour is genuinely worn and
    these four assertions measure the cap and nothing else.
    """
    assert _ac(_kit(MEDIUM), dex=20, base_ac=10) == 14
    assert _ac(_kit(MEDIUM), dex=16, base_ac=10) == 14  # +3, still inside the cap
    assert _ac(_kit(MEDIUM), dex=14, base_ac=10) == 14  # +2, exactly the cap
    assert _ac(_kit(MEDIUM), dex=12, base_ac=10) == 13  # +1, under the cap


def test_light_armor_still_takes_the_whole_dexterity_modifier():
    """The cap belongs to medium armour. Light armour prints no cap, so all of Dexterity counts."""
    assert _ac(_kit(LIGHT), dex=20, base_ac=10) == 16
    assert _ac(_kit(LIGHT), dex=14, base_ac=10) == 13


def test_heavy_armor_ignores_dexterity_entirely():
    """Imperial Plate Battle Dress prints "18" with no Dexterity term."""
    for dex in (20, 16, 8):
        assert _ac(_kit(HEAVY), dex=dex, strength=18) == 18


# --- 2. a carried Shield gives its +2 --------------------------------------------

def test_starting_kit_shield_adds_two_to_the_ac_number():
    """The Shield in an ordinary starting kit is worth +2 AC, which it was not."""
    assert _ac(_kit(SHIELD), dex=20) == _ac(_kit(), dex=20) + 2


def test_shield_adds_its_two_on_top_of_worn_armour():
    assert _ac(_kit(LIGHT, SHIELD), dex=14) == _ac(_kit(LIGHT), dex=14) + 2


def test_treasure_slot_shield_and_kit_shield_agree():
    """Both storage paths give the same Shield bonus, so the number and the recorded passive cannot drift."""
    from combat import armour

    treasure = {"resolved_treasure_armor": {"chassis": dict(armour.catalog()[SHIELD])}}
    assert armour.shield_ac_bonus(treasure) == armour.shield_ac_bonus(_kit(SHIELD)) == 2


def test_an_owner_given_shield_counts_too():
    """``fix/hands`` reads owner-granted gear to decide whether a shield takes a hand.

    The same rows feed the AC number here, so the grip check and the number can
    never disagree about whether the character is holding a Shield.
    """
    from combat import armour

    granted = [{"record": {"chassis": {"armor_category": "shield"}}}]
    assert armour.carries_shield({"items": []}, granted) is True
    assert armour.shield_ac_bonus({"items": []}, granted) == 2
    assert armour.armor_class(13, {"items": []}, {"DEX": 3}, owner_items=granted) == 15
    # Owner-given body armour is not a Shield, and must not be mistaken for one.
    body = [{"record": {"chassis": {"armor_category": "medium"}}}]
    assert armour.carries_shield({"items": []}, body) is False


def test_the_compiled_ac_already_contains_the_shield_the_table_credits():
    """Break Guard and Sacrificial Shield take that recorded +2 back off, so the number must contain it too.

    AUDIT4 #2: the compiler emitted the ``shield_ac`` +2 passive for a starting-kit
    Shield while the AC number had none, so those riders pushed AC below the true
    value.  Landing the +2 inside the number is what makes the subtraction land
    on the unshielded value.
    """
    shielded = compile_character(_sheet({"items": [{"item_id": AXE, "name": "Fu", "quantity": 1},
                                                  {"item_id": SHIELD, "name": "Shield", "quantity": 1}]}), actor_id="actor:factory.hero")
    recorded = [row for row in shielded["typed_passives"] if row.get("block") == "shield_ac"]
    assert recorded == [{"feature_id": "shield_ac", "block": "shield_ac", "amount": 2}]
    unshielded = compile_character(_sheet({"items": [{"item_id": AXE, "name": "Fu", "quantity": 1}]}), actor_id="actor:factory.hero")
    assert shielded["actor_template"]["armor_class"] - sum(int(row["amount"]) for row in recorded) \
        == unshielded["actor_template"]["armor_class"]


# --- 3. the Strength requirement costs Speed, not AC ----------------------------

def test_falling_short_of_the_strength_requirement_costs_ten_feet_of_speed():
    """Imperial Plate needs Str 15. STR 14 is short of it, so Speed drops from 30 to 20; the AC is untouched."""
    assert _speed(_kit(HEAVY), strength=14) == 20
    assert _ac(_kit(HEAVY), strength=14) == 18


def test_meeting_the_strength_requirement_leaves_speed_alone():
    assert _speed(_kit(HEAVY), strength=15) == 30
    assert _speed(_kit(HEAVY), strength=18) == 30


def test_armour_without_a_strength_requirement_costs_no_speed():
    """Light armour prints "—"; a weak character wearing it is not slowed."""
    assert _speed(_kit(LIGHT), strength=8) == 30


def test_a_shield_alone_costs_no_speed():
    assert _speed(_kit(SHIELD), strength=8) == 30


def test_the_slowed_walker_never_goes_below_zero():
    assert _speed(_kit(HEAVY), strength=4, speed=5) == 0


# --- 4. one calculation applies: the best one the character can actually use ------

def test_worn_armour_replaces_the_unarmored_calculation_when_it_is_better():
    """One AC calculation applies, and the character wears the armour that is better for them.

    Light armour is 11 + Dexterity, so DEX 14 is AC 13 against a plain unarmored 10: the armour wins, is worn,
    and replaces the unarmored number rather than adding to it (14, not 10 + 13).
    """
    assert _ac(_kit(LIGHT), dex=14, base_ac=10) == 13


def test_armour_worse_than_the_unarmored_defense_is_carried_not_worn():
    """A Path's Unarmored Defense of 16 beats light armour's 13, so the armour is carried, not worn.

    ``owner 2026-10-02``: "a real player wouldn't wear worse armor".  Carrying it means it gives no AC, no
    Dexterity cap and no Strength requirement, and the unarmored calculation is the one that applies.
    """
    assert _ac(_kit(LIGHT), dex=14, base_ac=16) == 16
    assert _ac(_kit(HEAVY), dex=14, base_ac=20, strength=18) == 20  # the Plate's 18 loses to 20
    # It is genuinely carried: the item is still listed, just not marked worn.
    listing = compile_character(_sheet(_kit(HEAVY), dex=14, base_ac=20, strength=18),
                                actor_id="actor:factory.hero")["carrying"]
    assert [item["worn"] for item in listing["items"]] == [False]


def test_carried_armour_asks_for_no_strength_and_costs_no_speed():
    """A carried suit imposes nothing, so the plate's "Str 15" cannot slow a character who is not wearing it.

    STR 14 is below the plate's requirement but still carries its weight, so this is the Strength rule alone and
    not the encumbrance rule.
    """
    assert _speed(_kit(HEAVY), strength=14, base_ac=20) == 30  # carried: no requirement, so no penalty
    assert _speed(_kit(HEAVY), strength=14, base_ac=10) == 20  # worn: Str 15 wanted, -10 ft


def test_an_unarmored_character_keeps_their_own_calculation():
    """With nothing worn there is no alternate calculation to switch to."""
    assert _ac(_kit(), dex=20, base_ac=16) == 16
    assert _ac(_kit(SHIELD), dex=20, base_ac=16) == 18  # the shield still adds


# --- the shared computation ------------------------------------------------------

def test_compiled_medium_armor_and_shield_total():
    """Compiler arithmetic; real sheet/fight consumers have separate regressions."""
    kit = _kit(MEDIUM, SHIELD)
    compiled = compile_character(_sheet(kit, dex=20), actor_id="actor:factory.hero")["actor_template"]["armor_class"]
    assert compiled == 16
