"""MMX34: armor class, round 2 -- the review findings, the design default, and AUDIT9 rows 1, 2 and 5.

Each test drives the real consumer the bug showed in: ``compile_character`` for the sheet, a real
``Gate4ControllerEngine`` fight for anything that happens mid-fight, and ``equipment_list`` for the sheet's
Items tab.  Nothing here calls a helper and asserts the helper agrees with itself.

  Review finding 1  A dropped or disarmed shield still granted its +2 AC, and could be subtracted twice.
  Review finding 2  The tests compared the compiler with its own helpers instead of the sheet and the table.
  B (lead, 2026-10-02)  Armour worse than the character's own unarmored defense is CARRIED, not worn.
  AUDIT9 row 1     Dragon Scales' and Stone Skin's +1 AC was never applied in the fight.
  AUDIT9 row 2     The compiler read the sheet's base AC, losing every always-on bonus.
  AUDIT9 row 5     A missing maximum HP became a 1-HP fighter with nothing said.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from combat import armour, carry
from combat.factory_compiler import compile_character, equipment_list
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.mmx34"
SHIELD = "tianxia.mortal.armor.shield"
AXE = "tianxia.mortal.weapon.fu"
# 12 + Dex modifier (max +2): medium armour, so the Dex cap is live.
MEDIUM = "tianxia.mortal.armor.beast_hide_harness"
# 11 + Dex modifier: light armour.
LIGHT = "tianxia.mortal.armor.lacquered_leather"
HEAVY = "tianxia.mortal.armor.imperial_plate_battle_dress"  # "18", "Str 15"
STONE_SKIN = "tianxia.subpath.body.yamabushi.feature.stone_skin"
DRAGON_SCALES = "tianxia.subpath.body.ryujin.feature.dragon_scales"
TEMPERED_FLESH = "tianxia.subpath.body.iron_shirt.feature.tempered_flesh"
UNARMORED = "tianxia.path.body_refining.feature.unarmored_defense"


_NAMES = {SHIELD: "Shield", AXE: "Fu", MEDIUM: "Beast-Hide Harness", LIGHT: "Lacquered Leather",
          HEAVY: "Imperial Plate Battle Dress"}


def _kit(*item_ids):
    """A starting kit.  The printed name is what the Drop and Pick up buttons say."""
    return {"items": [{"item_id": i, "name": _NAMES.get(i, i.rsplit(".", 1)[-1]), "quantity": 1} for i in item_ids]}


def _sheet(kit=None, *, dex=16, strength=16, base_ac=14, value=None, speed=30, hp=80, mids=()):
    """A real sheet.  ``base_ac`` is the unarmored calculation; ``value`` is the sheet's active AC
    (``base_ac`` plus whatever always-on bonuses the sheet has folded in)."""
    stats = {"abilities": [{"ability": a, "score": s, "modifier": (s - 10) // 2}
                           for a, s in (("STR", strength), ("DEX", dex), ("CON", 16), ("INT", 12), ("WIS", 14), ("CHA", 10))],
             "primary_resource": {"name": "Stamina", "maximum": 60},
             "armor_class": {"base_value": base_ac, **({"value": value} if value is not None else {})},
             "speed": {"walking_ft": speed}, "technique_save_dc": 16, "technique_attack_bonus": 8}
    if hp is not None:
        stats["hit_points"] = {"maximum": hp}
    out = {"proficiencies": {"armor": ["Shield"]}, "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Body Refining", "key_ability": "STR"},
           "ability_scores_and_statistics": stats,
           "path_and_subpath": {"path_feature_record_ids": list(mids)},
           "equipment": [{"starting_kit": kit or {"items": []}}],
           "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": [],
                                   "automatic_sphere_component_record_ids": []}}
    return out


def _bundle(sheet=None, actor_id=ME):
    return compile_character(sheet or _sheet(), actor_id=actor_id)


def _fight(sheet=None, seed="MMX34"):
    bundle = _bundle(sheet)
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _effective_ac(engine, actor_id=ME):
    """The AC a fight actually rolls against: the compiled number plus everything the ac hooks add."""
    actor = engine.state.actors[actor_id]
    return int(actor.armor_class) + int(engine._ac_modifier(actor))


def _do(engine, name):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME, target_ids=candidate.target_ids))


def _shielded(extra=()):
    return _sheet(_kit(AXE, SHIELD, *extra))


# ======================================================================== review finding 1: the shield's +2 follows possession

def test_a_dropped_shield_stops_granting_its_two_in_the_fight():
    """The +2 is inside the compiled AC, so a shield that leaves the fighter's hands has to be taken back
    through the ac hook.  Before this, dropping a shield left the fighter at the shielded number."""
    engine = _fight(_shielded())
    actor = engine.state.actors[ME]
    assert _effective_ac(engine) == int(actor.armor_class)  # in hand: the hook is inert
    _do(engine, "Drop Shield")
    assert _effective_ac(engine) == int(actor.armor_class) - 2


def test_picking_the_shield_back_up_restores_its_two():
    engine = _fight(_shielded())
    actor = engine.state.actors[ME]
    _do(engine, "Drop Shield")
    after_drop = _effective_ac(engine)
    _do(engine, "Pick up Shield")
    assert _effective_ac(engine) == after_drop + 2 == int(actor.armor_class)


def test_a_shield_taken_by_another_creature_stops_counting_too():
    """Possession is the fight's own state, not the drop action: another creature taking the shield
    (needle bind, open hand) is the same fact written a different way."""
    engine = _fight(_shielded())
    actor = engine.state.actors[ME]
    key = armour.shield_item_key(engine, actor)
    assert key, "the compiler must mark the shield in the item list for this to be findable"
    engine._apply_condition(actor, carry.DROPPED, "system:test", ME, expires_on="UNTIL_REMOVED",
                            data={"item_key": key, "item_name": "Shield", "held_by": AN,
                                  "dropped_at": actor.position.model_dump(mode="json")})
    assert _effective_ac(engine) == int(actor.armor_class) - 2


def test_a_broken_shield_and_a_dropped_one_lose_the_bonus_once_not_twice():
    """Sacrificial Shield breaks the shield; the shield can then also be dropped.  The +2 must go once."""
    engine = _fight(_shielded())
    actor = engine.state.actors[ME]
    _do(engine, "Drop Shield")
    engine._apply_condition(actor, armour.BROKEN_SHIELD, "system:test", ME, expires_on="UNTIL_REMOVED",
                            data={"label": "Shield broken: no Shield Bonus (-2 AC)"})
    assert _effective_ac(engine) == int(actor.armor_class) - 2


def test_a_broken_shield_still_in_hand_loses_its_bonus_once():
    engine = _fight(_shielded())
    actor = engine.state.actors[ME]
    engine._apply_condition(actor, armour.BROKEN_SHIELD, "system:test", ME, expires_on="UNTIL_REMOVED",
                            data={"label": "Shield broken: no Shield Bonus (-2 AC)"})
    assert _effective_ac(engine) == int(actor.armor_class) - 2


def test_a_fighter_carrying_no_shield_is_left_alone():
    """Inert for everyone who does not own the shield bonus: no row, no subtraction."""
    engine = _fight(_sheet(_kit(AXE)))
    assert _effective_ac(engine) == int(engine.state.actors[ME].armor_class)


def test_a_shield_row_whose_item_cannot_be_identified_keeps_its_bonus():
    """Nothing has said this fighter lost the shield, so nothing is taken away.

    A hand-built actor (as the Armored Aegis rider test builds one) has the ``shield_ac`` row but no item list to
    match it against, and a fight saved before the compiler marked the shield has none either.  Subtracting on
    "cannot tell" would silently take a bonus away from both.
    """
    engine = _fight(_sheet(_kit(AXE)))
    actor = engine.state.actors[ME]
    engine.typed_passive_rows.setdefault(ME, []).append(
        {"feature_id": "shield_ac", "block": "shield_ac", "amount": 2})
    assert armour.shield_item_key(engine, actor) is None
    assert armour.shield_bonus_earning(engine, actor) == 2
    assert _effective_ac(engine) == int(actor.armor_class)  # no subtraction


def test_guard_broken_takes_the_bonus_once_when_the_shield_is_also_dropped():
    """A talent that denies Shield AC and a dropped shield are the same +2; neither may take it twice."""
    from combat.ext import guard_broken

    engine = _fight(_shielded())
    actor = engine.state.actors[ME]
    engine.__dict__[guard_broken.CURRENT] = {"attacker": AN, "target": ME, "ranged": False, "axe": False}
    engine._apply_condition(actor, guard_broken.CONDITION, "system:test", AN, expires_on="UNTIL_REMOVED",
                            data={"shield": True, "cover": False, "next": False, "axe": False, "by": "source"})
    _do(engine, "Drop Shield")
    assert _effective_ac(engine) == int(actor.armor_class) - 2


# ======================================================================== review finding 2: the real consumers, and a table reload

def test_the_items_tab_says_which_armour_is_worn_and_carries_a_plain_note():
    """The sheet's Items tab is where a player looks.  The note names the armour, both numbers, and what the
    character is doing instead -- no internal ids, nothing to look up."""
    listing = equipment_list(_sheet(_kit(LIGHT), dex=20, base_ac=19))
    assert listing["items"][0]["worn"] is False
    assert listing["armor_note"] == ("Carrying Lacquered Leather -- your unarmored defense (AC 19) is better than "
                                     "wearing it (AC 16), so it gives you no Armor Class and no Armour penalties.")


def test_the_items_tab_wears_armour_that_is_better_and_says_nothing_extra():
    listing = equipment_list(_sheet(_kit(LIGHT), dex=20, base_ac=10))
    assert listing["items"][0]["worn"] is True
    assert "armor_note" not in listing


def test_the_note_never_appears_for_a_character_with_no_armour():
    listing = equipment_list(_sheet(_kit(AXE)))
    assert "armor_note" not in listing


def _table_match(tmp_path, bundle):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(
        [bundle], [ME, AN], {ME: "team:a", AN: "team:b"},
        {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [AN],
        control_modes={ME: "MANUAL", AN: "MANUAL"}, match_seed="EQUIPMENT-PERSISTENCE",
        display_name="Equipment regression", maximum_rounds=20)["match_id"]
    table = TabletopService(combat, tmp_path)
    from tests.test_lock2_persistence import act
    if table.state(mid)["menu"]["actor_id"] != ME:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid


def _table_do(table, mid, name):
    state = table.state(mid)
    option = next(o for g in state["menu"]["actions"] for o in g["options"]
                  if o["label"] == name)
    return table.act(mid, option["candidate_id"], state["menu"]["decision_id"],
                     state["menu"]["state_version"], state["last_sequence"])


def test_dropped_shield_and_strength_speed_penalty_survive_table_commit_reload(tmp_path):
    from combat.gate5_service import CombatService
    combat, table, mid = _table_match(tmp_path, _bundle(_sheet(_kit(HEAVY, AXE, SHIELD), base_ac=10, strength=14)))
    assert _table_do(table, mid, "Drop Shield")["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[ME]
    assert actor.speed_ft == 20
    assert _effective_ac(loaded.engine) == 18
    [drop] = [c for c in actor.conditions.values() if c.condition_id == carry.DROPPED]
    assert drop.data["item_key"] == SHIELD and drop.expires_on == "UNTIL_REMOVED"
    [marker] = [i["shield"] for i in loaded.engine.typed_bundle_documents[0]["carrying"]["items"] if i.get("shield")]
    assert type(marker) is int and marker == 1
    assert loaded.mechanical.replay()["status"] == "PASS"


def _do_on(engine, name, actor_id):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name and c.actor_id == actor_id)
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=actor_id, target_ids=candidate.target_ids))


# ======================================================================== B: worse armour is carried, not worn

def test_armour_worse_than_the_unarmored_defense_gives_no_ac():
    assert _bundle(_sheet(_kit(HEAVY), dex=14, base_ac=20, strength=18))["actor_template"]["armor_class"] == 20
    assert _bundle(_sheet(_kit(HEAVY), dex=14, base_ac=10, strength=18))["actor_template"]["armor_class"] == 18


def test_carried_armour_costs_no_speed_even_below_its_strength_requirement():
    """STR 14 is short of the plate's Str 15 but still carries its weight, so this is the Strength rule alone."""
    carried = _bundle(_sheet(_kit(HEAVY), dex=14, base_ac=20, strength=14))["actor_template"]
    assert carried["speed_ft"] == 30
    worn = _bundle(_sheet(_kit(HEAVY), dex=14, base_ac=10, strength=14))["actor_template"]
    assert worn["speed_ft"] == 20


def test_a_carried_suit_still_counts_as_carried_weight_and_still_gets_dropped():
    sheet = _sheet(_kit(HEAVY), dex=14, base_ac=20, strength=18)
    bundle = _bundle(sheet)
    assert bundle["carrying"]["items"][0]["worn"] is False
    assert bundle["carrying"]["armor_note"]
    engine = _fight(sheet)
    before = carry.weight(engine, engine.state.actors[ME])
    assert before == float(bundle["carrying"]["items"][0]["weight_lb"]) > 0
    _do(engine, "Drop Imperial Plate Battle Dress")
    assert carry.weight(engine, engine.state.actors[ME]) == 0
    assert _effective_ac(engine) == 20


def test_armour_that_beats_the_unarmored_defense_is_worn_as_before():
    """The rule only bites when the armour is worse; a real upgrade is put on."""
    assert _bundle(_sheet(_kit(HEAVY), dex=14, base_ac=10, strength=18))["carrying"]["items"][0]["worn"] is True


# ======================================================================== AUDIT9 row 1: Dragon Scales and Stone Skin

def test_stone_skin_adds_its_one_to_armor_class_while_unarmored():
    engine = _fight(_sheet(_kit(AXE), dex=14, base_ac=17, mids=[UNARMORED, STONE_SKIN]))
    assert _effective_ac(engine) == 18


def test_dragon_scales_adds_its_one_to_armor_class_while_unarmored():
    engine = _fight(_sheet(_kit(AXE), dex=14, base_ac=17, mids=[UNARMORED, DRAGON_SCALES]))
    assert _effective_ac(engine) == 18


def test_those_features_still_grant_their_resistance():
    """The ac row was added next to the existing one, not instead of it."""
    from combat import typed_reactions

    engine = _fight(_sheet(_kit(AXE), dex=14, base_ac=17, mids=[UNARMORED, STONE_SKIN]))
    kinds = {(row.get("kind"), tuple(row.get("damage_types") or ()))
             for row in typed_reactions._rows(engine, ME, "defense")}
    assert _effective_ac(engine) == 18
    assert ("resistance", ("COLD",)) in kinds


def test_tempered_flesh_still_works_the_same_way():
    """The third +1 feature is the one that already worked; it must not double up."""
    engine = _fight(_sheet(_kit(AXE), dex=14, base_ac=17, mids=[UNARMORED, TEMPERED_FLESH]))
    assert _effective_ac(engine) == 18


def test_the_bonus_stops_when_the_character_wears_armour():
    """Both features are typed "while unarmored", so wearing armour turns them off."""
    engine = _fight(_sheet(_kit(MEDIUM, AXE), dex=14, base_ac=10, mids=[STONE_SKIN]))
    assert _effective_ac(engine) == 14  # the harness is 12 + Dex capped at 2, with no feature bonus


# ======================================================================== AUDIT9 row 2: the always-on bonuses survive

def test_an_always_on_bonus_is_not_lost_to_worn_armour():
    """The sheet's active AC is its base calculation plus the bonuses it folded in; the bonus applies after the
    calculation is chosen, so replacing the calculation must not throw it away."""
    sheet = _sheet(_kit(MEDIUM), dex=14, base_ac=10, value=15)  # unarmored 10, plus an always-on +5
    assert _bundle(sheet)["actor_template"]["armor_class"] == 19  # harness 12 + Dex 2 = 14, then the +5


def test_the_always_on_bonus_applies_with_no_armour_too():
    assert _bundle(_sheet(_kit(AXE), dex=14, base_ac=10, value=15))["actor_template"]["armor_class"] == 15


def test_a_sheet_that_publishes_only_one_number_still_works():
    sheet = _sheet(_kit(AXE), base_ac=12)
    assert "value" not in sheet["ability_scores_and_statistics"]["armor_class"]
    assert _bundle(sheet)["actor_template"]["armor_class"] == 12


# ======================================================================== AUDIT9 row 5: no more silent 1-HP fighters

def test_a_missing_hit_point_maximum_is_reported_instead_of_being_one():
    from app.core import FoundryError
    with pytest.raises(FoundryError, match="no valid maximum Hit Points"):
        _bundle(_sheet(_kit(AXE), hp=None))


def test_a_zero_hit_point_maximum_is_reported_too():
    from app.core import FoundryError
    with pytest.raises(FoundryError, match="no valid maximum Hit Points"):
        _bundle(_sheet(_kit(AXE), hp=0))


def test_a_normal_character_gets_no_hit_point_diagnostic():
    assert not [n for n in _bundle(_sheet(_kit(AXE)))["diagnostics"]["notes"] if "Hit Points" in n]


# ======================================================================== the shared computation, and the roster it was measured on

def test_the_roster_package_arms_used_by_the_reports_still_compiles():
    """The measured packages on disk compile through this same path, so the roster numbers in the report are
    produced by the code under test and not by a separate script."""
    roster = Path("/var/tmp/auto-audit/astra/lock3-inputs/portable_characters")
    packages = sorted(roster.glob("*/current.zip")) if roster.is_dir() else []
    if not packages:
        return  # the measured inputs are not on this machine; the compile itself is covered above
    for package in packages[:3]:
        sheet = json.loads(zipfile.ZipFile(package).read("Tianxia_Owner_Character_Sheet_v1.json"))
        template = _bundle(sheet)["actor_template"]
        assert int(template["armor_class"]) >= 5
        assert int(template["maximum_hp"]) >= 1
