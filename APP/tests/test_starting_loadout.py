"""Public-safe starting-gear regressions: real table commits and cold reloads."""
from copy import deepcopy

import pytest

from combat.ext.hand_occupancy import occupancy, weapon_allowed, weapon_grips
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from factory_authoring.starting_kits import item_definition
from tests.h1_support import ROOT, sheet
from tests.hunt51_grapple_support import fight, on_turn, send, verify_reloaded

W = "tianxia.mortal.weapon."
SHIELD = "tianxia.mortal.armor.shield"
ACTOR = "actor:factory.luna38-a"


def owner(items, **choices):
    return sheet([], cl=18, score=30, kit={"starting_kit": {"items": [
        {"item_id": key, "name": item_definition(key)["name"], "quantity": 1} for key in items], **choices}})


def bundle(doc, **kwargs):
    return compile_character(doc, actor_id=ACTOR, **kwargs)


def cold(user, match):
    return CombatService(ROOT, user)._load_session(match).engine


def options(table, match):
    return [{**option, "source_definition_id": group["source_definition_id"]}
            for group in table.state(match)["menu"]["actions"] for option in group["options"]]


def attack_and_reload(tmp_path, doc, expected, *, owner_items=None):
    compiled = bundle(doc, owner_items=owner_items)
    user, service, table, match, ids = fight(tmp_path, "start-gear", saved_bundle=compiled)
    on_turn(table, match, ids[0])
    engine = cold(user, match)
    actor = engine.state.actors[ids[0]]
    ready = weapon_grips(engine, actor)
    primary = compiled["carrying"]["starting_loadout"]["primary_weapon"]
    assert primary.endswith(expected)
    assert primary in ready
    assert weapon_allowed(engine, actor, engine.action_catalog[primary])
    assert not any(key.startswith("occupied:overflow:") for key in occupancy(engine, actor))
    assert any(row["source_definition_id"] == primary and row.get("target_ids") == [ids[2]]
               for row in options(table, match))
    send(table, match, lambda row: row["source_definition_id"] == primary and row.get("target_ids") == [ids[2]])
    verify_reloaded(user, service, match)
    reloaded = cold(user, match)
    assert weapon_grips(reloaded, reloaded.state.actors[ids[0]]) == ready
    assert any(event.event_type == "ATTACK_ROLLED" and event.source_definition_id == primary for event in reloaded.events)
    return compiled, reloaded, table, match, ids


def test_staff_and_two_spears_start_with_usable_treasure_spear(tmp_path):
    doc = owner([W + "gun", W + "duan_qiang", W + "qiang"])
    doc["equipment"][0]["starting_kit"]["resolved_treasure_weapon"] = {
        "name": "Blood Jade Qiang +1", "chassis": item_definition(W + "qiang"),
        "refinement_bonus": 1, "enchantments": []}
    compiled, engine, table, match, ids = attack_and_reload(tmp_path, doc, ".weapon.qiang.treasure")
    ready = weapon_grips(engine, engine.state.actors[ids[0]])
    assert list(ready) == [compiled["carrying"]["starting_loadout"]["primary_weapon"]]
    assert len([item for item in compiled["carrying"]["items"] if item.get("weapon_action")]) == 3
    labels = [row["label"] for row in options(table, match)]
    assert any("Draw Gun" in label for label in labels)
    assert any("Draw Duan Qiang" in label for label in labels)


def test_sword_and_shield_keep_both_and_attack(tmp_path):
    compiled, engine, _, _, ids = attack_and_reload(tmp_path, owner([W + "jian", SHIELD]), ".weapon.jian")
    assert compiled["carrying"]["starting_loadout"]["held_items"] == [SHIELD]
    assert sum(len(row) for row in occupancy(engine, engine.state.actors[ids[0]]).values()) == 2


@pytest.mark.parametrize("choice", ["primary_weapon", "wielded", "last_loadout"])
def test_saved_choice_beats_stronger_weapon_after_commit_and_cold_reload(tmp_path, choice):
    doc = owner([W + "gun", W + "duan_qiang", W + "qiang"], **{choice: W + "gun" if choice == "primary_weapon" else [W + "gun"]})
    compiled, engine, _, _, ids = attack_and_reload(tmp_path, doc, ".weapon.gun")
    assert list(weapon_grips(engine, engine.state.actors[ids[0]])) == [compiled["carrying"]["starting_loadout"]["primary_weapon"]]


def test_two_handed_primary_stows_shield_without_phantom_occupancy(tmp_path):
    from combat import carry
    compiled, engine, _, _, ids = attack_and_reload(tmp_path, owner([W + "qiang", SHIELD]), ".weapon.qiang")
    assert compiled["carrying"]["starting_loadout"]["held_items"] == []
    assert carry.owned_item_location(engine.state.actors[ids[0]], SHIELD) == "carried"
    assert sum(len(row) for row in occupancy(engine, engine.state.actors[ids[0]]).values()) == 1


def test_light_pair_keeps_legal_offhand(tmp_path):
    compiled, engine, _, _, ids = attack_and_reload(tmp_path, owner([W + "bi_shou", W + "fu"]), ".weapon.fu")
    assert len(weapon_grips(engine, engine.state.actors[ids[0]])) == 2


def test_no_legal_weapon_starts_hands_free_and_explains_why():
    from combat.gate2_runtime_models import ActionDefinition
    from combat.starting_loadout import select_loadout
    compiled = bundle(owner([W + "qiang"]))
    plan = select_loadout([ActionDefinition.model_validate(row) for row in compiled["action_catalog"]],
                          compiled["carrying"], ACTOR, hands=1)
    assert plan["weapons"] == [] and plan["held_items"] == []
    assert "hands free" in plan["note"] and "none of the carried weapons" in plan["note"]


def test_factory_grow_and_table_sheet_name_starting_weapon():
    from character_sheet.service import CharacterSheetService
    from combat.tabletop import sheet_summary
    doc = owner([W + "gun", W + "qiang"], primary_weapon=W + "gun")
    original = deepcopy(doc)
    CharacterSheetService._publish_starting_loadout(None, doc)
    assert doc["equipment"] == original["equipment"]
    assert "Gun" in doc["starting_loadout"]["note"]
    compiled = bundle(doc)
    assert sheet_summary(doc, bundle=compiled)["starting_loadout"]["note"] == doc["starting_loadout"]["note"]
    assert "Starting equipment" in (ROOT / "static/app.js").read_text()
    assert "Starting equipment" in (ROOT / "static/tabletop/sheet.js").read_text()
