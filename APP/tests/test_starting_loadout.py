"""Public-safe starting-gear regressions: real table commits and cold reloads."""
from copy import deepcopy

import pytest

from combat.ext.hand_occupancy import occupancy, weapon_allowed, weapon_grips
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
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
    assert not any(row.condition_id == "condition:typed.equipment_grip"
                   for fighter in engine.state.actors.values() for row in fighter.conditions.values())
    readiness_events = [event for event in engine.events if event.event_type == "EQUIPMENT_READINESS_SET"]
    assert len(readiness_events) == 1
    assert readiness_events[0].actor_id == ids[0]
    assert isinstance(readiness_events[0].payload["readiness"], dict)
    assert "Starts wielding" in readiness_events[0].payload["log"]
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


def test_sword_and_shield_start_with_the_shield_in_use_and_its_armor_class(tmp_path):
    """A one-handed sword leaves a hand for the Shield, so a trained fighter starts with it held, keeps its
    printed +2 Armor Class, and still has it after a table commit and a cold reload. Only a loadout the hands
    cannot hold (a Two-Handed weapon, see below) may stow the Shield."""
    from combat.ext.shield_wielding import wielding_a_shield

    doc = owner([W + "jian", SHIELD])
    doc["proficiencies"] = {"armor": ["Shield"]}
    compiled = bundle(doc)
    assert compiled["carrying"]["starting_loadout"]["held_items"] == [SHIELD]
    assert compiled["actor_template"]["armor_class"] == bundle(owner([W + "jian"]))["actor_template"]["armor_class"] + 2
    _, engine, _, _, ids = attack_and_reload(tmp_path, doc, ".weapon.jian")
    actor = engine.state.actors[ids[0]]
    assert wielding_a_shield(engine, actor)
    assert engine._ac_modifier(actor) == 0  # the +2 is inside the compiled Armor Class, nothing takes it back
    assert actor.armor_class == compiled["actor_template"]["armor_class"]


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


def test_explicit_wielded_kit_choices_ready_both_carried_weapons(tmp_path):
    """A saved loadout that names both weapons draws both.

    Only a Light or Paired twin, or the owner's explicit choice, joins the primary (combat/starting_loadout.py);
    the riders regressions carry a Flying Dart and an axe and attack with the second one on their first turn,
    so their sheets state this same saved choice instead of relying on an undrawn weapon being attackable.
    """
    doc = owner([W + "fei_biao", W + "fu"])
    for item in doc["equipment"][0]["starting_kit"]["items"]:
        item["wielded"] = True
    compiled, engine, table, match, ids = attack_and_reload(tmp_path, doc, ".weapon.fei_biao")
    plan = compiled["carrying"]["starting_loadout"]
    assert plan["preferences"] == [W + "fei_biao", W + "fu"]
    assert len(plan["weapons"]) == 2
    # Both grips survive the commit and the cold reload the helper checks.
    assert len(weapon_grips(engine, engine.state.actors[ids[0]])) == 2


def test_focus_occupies_only_the_available_offhand_after_reload(tmp_path):
    focus = "tianxia.mortal.focus.qi_focus_jade_orb"
    compiled, engine, _, _, ids = attack_and_reload(tmp_path, owner([W + "jian", focus]), ".weapon.jian")
    actor = engine.state.actors[ids[0]]
    assert compiled["carrying"]["starting_loadout"]["held_items"] == [focus]
    assert sum(len(row) for row in occupancy(engine, actor).values()) == 2
    assert not any(row.condition_id == "condition:typed.disarmed" for row in actor.conditions.values())
    from combat.ext import ai_restraint
    grab = next((a for a in engine.action_catalog.values()
                 if a.owner_id == actor.entity_id and a.source_definition_id.endswith(".improvised.grab")), None)
    assert grab is not None
    assert ai_restraint._has_own_attack(engine, actor)
    assert ai_restraint.restraint(engine, actor, type("Candidate", (), {"source_definition_id": grab.source_definition_id})(), grab) is False


def test_saved_given_weapon_choice_uses_its_exact_inventory_key(tmp_path):
    given = [{"kind": "weapon", "equipped": True,
              "record": {"name": "Chosen short spear", "chassis": item_definition(W + "duan_qiang"),
                         "refinement_bonus": 0, "enchantments": []}}]
    compiled, engine, _, _, ids = attack_and_reload(tmp_path, owner([W + "qiang"]),
                                                   ".weapon.duan_qiang.given1", owner_items=given)
    primary = compiled["carrying"]["starting_loadout"]["primary_weapon"]
    assert next(item for item in compiled["carrying"]["items"] if item["key"] == "given.0")["weapon_action"] == primary
    assert list(weapon_grips(engine, engine.state.actors[ids[0]])) == [primary]


def test_proficiency_precedes_attack_damage_and_treasure_breaks_ties():
    from combat.gate2_runtime_models import ActionDefinition
    from combat.starting_loadout import select_loadout
    compiled = bundle(owner([W + "gun", W + "qiang"]))
    actions = [ActionDefinition.model_validate(row) for row in compiled["action_catalog"]]
    for action in actions:
        if action.source_definition_id.endswith(".weapon.qiang"):
            action.parameters["typed"]["proficient"] = False
            action.parameters["typed"]["numbers"]["attack_bonus"] = 99
        elif action.source_definition_id.endswith(".weapon.gun"):
            action.parameters["typed"]["proficient"] = True
    plan = select_loadout(actions, compiled["carrying"], ACTOR)
    assert plan["primary_weapon"].endswith(".weapon.gun")
    for action in actions:
        if action.source_definition_id.endswith((".weapon.qiang", ".weapon.gun")):
            action.parameters["typed"]["proficient"] = True
            action.parameters["typed"]["numbers"]["attack_bonus"] = 10
            action.parameters["expected_damage"] = 10
    for item in compiled["carrying"]["items"]:
        if item.get("weapon_action", "").endswith(".weapon.qiang"):
            item["treasure"] = True
    assert select_loadout(actions, compiled["carrying"], ACTOR)["primary_weapon"].endswith(".weapon.qiang")


def test_no_legal_weapon_starts_hands_free_and_explains_why():
    from combat.gate2_runtime_models import ActionDefinition
    from combat.starting_loadout import select_loadout
    compiled = bundle(owner([W + "qiang"]))
    plan = select_loadout([ActionDefinition.model_validate(row) for row in compiled["action_catalog"]],
                          compiled["carrying"], ACTOR, hands=1)
    assert plan["weapons"] == [] and plan["held_items"] == []
    assert "hands free" in plan["note"] and "none of the carried weapons" in plan["note"]


def test_unusable_starting_weapon_is_stowed_with_a_table_log(tmp_path):
    compiled = bundle(owner([W + "qiang"]))
    # A valid generic hands requirement exceeding this actor's anatomy.
    for action in compiled["action_catalog"]:
        if action["source_definition_id"].endswith(".weapon.qiang"):
            action["parameters"]["requires_hands"] = 3
            action["parameters"]["typed"]["weapon"]["properties"] = ""
    user, service, table, match, ids = fight(tmp_path, "no-legal-start", saved_bundle=compiled)
    on_turn(table, match, ids[0])
    engine = cold(user, match)
    assert not weapon_grips(engine, engine.state.actors[ids[0]])
    assert occupancy(engine, engine.state.actors[ids[0]]) == {}
    assert any("none of the carried weapons" in str(event.payload.get("log")) for event in engine.events)
    send(table, match)  # commit and cold reload must not draw the unusable weapon
    verify_reloaded(user, service, match)
    engine = cold(user, match)
    assert not weapon_grips(engine, engine.state.actors[ids[0]])


def test_unarmed_equipment_initializer_is_idempotent(tmp_path):
    from combat.ext.equipment_hands import ready_starting_equipment
    user, _, _, match, _ = fight(tmp_path, "shield-only-start", saved_bundle=bundle(owner([SHIELD])))
    engine = cold(user, match)
    before = engine.state.model_dump(mode="json")
    event_count = len(engine.events)
    ready_starting_equipment(engine)
    assert len(engine.events) == event_count
    assert engine.state.model_dump(mode="json") == before


def test_factory_grow_and_table_sheet_name_starting_weapon():
    from character_sheet.service import CharacterSheetService
    from combat.tabletop import sheet_summary
    doc = owner([W + "gun", W + "qiang"], primary_weapon="action:typed.previous_actor.weapon.gun")
    original = deepcopy(doc)
    sealed = doc
    service = object.__new__(CharacterSheetService)
    doc = service._with_starting_loadout(doc)
    assert doc is not sealed
    assert sealed == original
    assert "starting_loadout" not in original
    assert doc["equipment"] == original["equipment"]
    assert "Gun" in doc["starting_loadout"]["note"]
    compiled = bundle(doc)
    assert sheet_summary(doc, bundle=compiled)["starting_loadout"]["note"] == doc["starting_loadout"]["note"]
    assert "Starting equipment" in (ROOT / "static/app.js").read_text()
    assert "Starting equipment" in (ROOT / "static/tabletop/sheet.js").read_text()


def test_melee_thrown_spear_keeps_its_melee_and_thrown_attacks():
    """A simple spear (duan qiang) has no proficiency class in the book: it must still get its attack action and,
    as a melee-Thrown weapon, a melee attack too. Before the fix it was dropped from the carried weapons entirely."""
    compiled = bundle(owner([W + "gun", W + "duan_qiang"]))
    spear = [item for item in compiled["carrying"]["items"] if item["item_id"] == W + "duan_qiang"][0]
    assert spear.get("weapon_action", "").endswith(".weapon.duan_qiang")
    actions = {row["source_definition_id"]: row for row in compiled["action_catalog"]}
    assert actions[spear["weapon_action"]]["range_ft"] == 5
    assert actions[spear["weapon_action"] + "#thrown"]["range_ft"] == 60


def test_saved_given_spear_stays_readied_after_attack_and_cold_reload(tmp_path):
    """A given simple spear (duan qiang) is a melee weapon too: attacking with it and reloading must keep it drawn."""
    given = [{"kind": "weapon", "equipped": True, "record": {
        "name": "Chosen short spear", "chassis": item_definition(W + "duan_qiang"), "refinement_bonus": 0,
        "enchantments": []}}]
    compiled, engine, _, _, ids = attack_and_reload(tmp_path, owner([W + "qiang"]), ".weapon.duan_qiang.given1",
                                                     owner_items=given)
    assert list(weapon_grips(engine, engine.state.actors[ids[0]])) == [compiled["carrying"]["starting_loadout"]["primary_weapon"]]
