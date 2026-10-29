"""Items tab (owner 2026-09-24): make treasures from the rules and give them to characters."""

import json
import zipfile

import pytest

from app.core import FoundryError
from combat.factory_compiler import compile_character
from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService
from factory_authoring import owner_items as O
from tests.test_factory_combat_compiler import SHEET
from tests.test_factory_live_match import ROOT, _install

DAGGER = "tianxia.mortal.weapon.bi_shou"
HARNESS = "tianxia.mortal.armor.beast_hide_harness"


def _frost_dagger(grade="Saint"):
    choices = O.weapon_choices(DAGGER, grade, None, [])
    frost = next(row["enchantment_id"] for row in choices["enchantments"] if row["name"] == "Frost-Meridian Inscription")
    return {"kind": "weapon", "chassis_id": DAGGER, "grade": grade, "material_id": choices["material_id"], "enchantment_ids": [frost]}


def test_dagger_plus_two_frost_is_made_from_the_rules():
    item = O.make_item(_frost_dagger())
    record = item["record"]
    assert item["name"] == "Frost-Meridian Bi Shou +2"
    assert record["refinement_bonus"] == 2 and record["enchantment_capacity"] >= 3
    assert [row["name"] for row in record["enchantments"]] == ["Frost-Meridian Inscription"]


def test_the_grade_limits_how_many_enchantments_fit():
    spec = _frost_dagger("Spiritual")  # +1, one slot
    extra = next(row["enchantment_id"] for row in O.weapon_choices(DAGGER, "Spiritual", spec["material_id"], [])["enchantments"]
                 if row["enchantment_id"] not in spec["enchantment_ids"] and row["equivalent_bonus"] == 1)
    with pytest.raises(FoundryError):
        O.make_item({**spec, "enchantment_ids": [*spec["enchantment_ids"], extra]})
    assert O.weapon_choices(DAGGER, "Spiritual", spec["material_id"], spec["enchantment_ids"])["enchantments"] == []


def test_given_items_are_kept_per_character_and_one_armour_is_worn(tmp_path):
    store = O.OwnerItemStore(tmp_path / "owner_items")
    dagger = store.give("hero", _frost_dagger())
    choices = O.armour_choices(HARNESS, "Saint", None, [])
    first = store.give("hero", {"kind": "armour", "chassis_id": HARNESS, "grade": "Saint", "material_id": choices["material_id"]})
    second = store.give("hero", {"kind": "armour", "chassis_id": HARNESS, "grade": "Spiritual", "material_id": O.armour_choices(HARNESS, "Spiritual", None, [])["material_id"]})
    worn = [row["item_uid"] for row in store.items("hero") if row.get("equipped")]
    assert worn == [second["item_uid"]]
    store.equip("hero", first["item_uid"])
    assert [row["item_uid"] for row in store.items("hero") if row.get("equipped")] == [first["item_uid"]]
    store.remove("hero", dagger["item_uid"])
    assert all(row["kind"] == "armour" for row in store.items("hero"))
    assert store.items("someone-else") == []
    wondrous = O.catalog()["wondrous"][0]["name"]
    assert store.give("hero", {"kind": "wondrous", "item_name": wondrous})["name"] == wondrous


def test_given_weapons_and_armour_fight(tmp_path):
    items = [{"kind": "weapon", **O.make_item(_frost_dagger())}]
    choices = O.armour_choices(HARNESS, "Saint", None, [])
    items.append({"kind": "armour", "equipped": True, **O.make_item({"kind": "armour", "chassis_id": HARNESS, "grade": "Saint", "material_id": choices["material_id"]})})
    plain = compile_character(SHEET, actor_id="actor:factory.t")
    armed = compile_character(SHEET, actor_id="actor:factory.t", owner_items=items)
    dagger = next(row for row in armed["action_catalog"] if row["display_name"] == "Frost-Meridian Bi Shou +2 attack")
    on_hit = dagger["parameters"]["typed"]["effects"][0]["on_hit"]
    # +2 to hit and damage, 1d4 cold and a real -5 ft Speed penalty automated on a hit (forged-worker 2026-09-29:
    # combat/factory_compiler.py _enchantment_on_hit); the printed multi-hit stacking cap stays a GM-only rider.
    assert any(row.get("type") == "damage" and row.get("dice") == {"count": 1, "sides": 4} and row.get("damage_types") == ["cold"] for row in on_hit)
    assert any(row.get("type") == "speed" and row.get("flat") == -5 for row in on_hit)
    assert any(row.get("type") == "rider" and "stack" in row.get("evidence", "").lower() for row in on_hit)
    assert dagger["parameters"]["typed"]["weapon"]["damage"]["modifier"] >= 2
    assert armed["actor_template"]["armor_class"] != plain["actor_template"]["armor_class"] or armed["actor_template"]["armor_class"] >= 16

    # A test fight picks up what the owner gave.
    _install(tmp_path, "left")
    _install(tmp_path, "right")
    store = O.OwnerItemStore(tmp_path / "owner_items")
    store.give("left", _frost_dagger())
    view = CombatService(ROOT, tmp_path).create_factory_match(project_ids=["left"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "right"], match_seed="ITEMS")
    bundles = json.loads((tmp_path / "Combat").rglob("Typed_Character_Bundles.json").__next__().read_text())
    left = next(row for row in bundles if row["actor_id"] == FACTORY_ACTOR_PREFIX + "left")
    assert any(row["display_name"] == "Frost-Meridian Bi Shou +2 attack" for row in left["action_catalog"])
    assert view["match_id"]


def test_custom_items_can_be_made_or_imported_and_given(tmp_path):
    """Owner 2026-09-24: an open library of wondrous items an AI GM can write and the owner imports."""
    library = O.CustomItemLibrary(tmp_path / "custom_items")
    ai_reply = O.CUSTOM_EXAMPLE  # the exact shape the "Copy AI instructions" prompt asks for
    added = library.add(O.parse_import(ai_reply), source="import")
    assert [row["name"] for row in added] == ["Cloud-Step Anklet"] and added[0]["source"] == "import"
    # One loose item object (as an AI might answer) is accepted too.
    library.add(O.parse_import({"name": "Ember Pill", "kind": "consumable", "grade": "Mortal", "text": "Regain 1d4 HP."}))
    assert len(library.items()) == 2
    for bad in ({"name": "X", "text": "t", "grade": "Divine"}, {"name": "", "text": "t"}, {"name": "X", "text": "t", "attunement_slots": 9},
                {"name": "X", "text": "t", "kind": "weapon"}):
        with pytest.raises(FoundryError):
            library.add([bad])
    store = O.OwnerItemStore(tmp_path / "owner_items")
    given = store.give("hero", {"kind": "wondrous", "custom_id": added[0]["custom_id"]}, library)
    assert given["name"] == "Cloud-Step Anklet" and given["record"]["text"].startswith("Once per short rest")
    library.remove(added[0]["custom_id"])
    assert store.items("hero")[0]["name"] == "Cloud-Step Anklet"  # a given copy stays with the character
