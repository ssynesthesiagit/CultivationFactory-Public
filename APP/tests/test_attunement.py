"""Attunement (owner 2026-09-28, tonight's list #1): four slots; a treasure that needs attunement gives its bonuses only
while attuned, otherwise it fights as its base item. combat/factory_compiler.py attunement / _unattuned, the Items tab's
Attuned toggles (combat/tabletop_service.py save_attunement)."""

import copy
from types import SimpleNamespace

import pytest

from combat.factory_compiler import attunement, compile_character, equipment_list
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopError, TabletopService
from factory_authoring.treasure_catalog import ATTUNEMENT_SLOTS
from tests.test_zones import SHEET

ME = "actor:factory.attuner"
ARMOR = {"chassis": {"armor_category": "light", "armor_class": "12 + Dex modifier", "item_id": "tianxia.mortal.armor.hidden_brigandine_robes",
                     "name": "Hidden Brigandine Robes", "weight": "13 lb."},
         "name": "Hidden Brigandine Robes +1", "refinement_bonus": 1, "enchantments": [], "enhancements": []}


def _wondrous(name: str, slots: int) -> dict:
    return {"name": name, "attunement_slots": slots, "item_type": "Wondrous Item", "text": "A test treasure.",
            "treasure_id": f"tianxia.treasure.wondrous.test.{name.lower().replace(' ', '_')}"}


def _sheet(*wondrous: dict) -> dict:
    kit = {"items": [], "resolved_treasure_armor": copy.deepcopy(ARMOR), "resolved_treasure_purchases": {"wondrous": list(wondrous)}}
    return {**SHEET, "equipment": [{"starting_kit": kit}]}


def _kit(sheet: dict) -> dict:
    return sheet["equipment"][0]["starting_kit"]


def test_by_default_every_treasure_that_fits_is_attuned_in_order():
    sheet = _sheet(_wondrous("Hand Furnace", 0), _wondrous("Jade Flute", 1), _wondrous("Heavy Crown", 2), _wondrous("Lotus Ring", 1))
    result = attunement(_kit(sheet), [], None)
    assert result["attunable"] == ["treasure_armor", "wondrous.1", "wondrous.2", "wondrous.3"]  # the furnace needs none
    assert result["attuned"] == ["treasure_armor", "wondrous.1", "wondrous.2"] and result["used"] == 4 == ATTUNEMENT_SLOTS
    chosen = attunement(_kit(sheet), [], ["wondrous.3", "wondrous.2"])
    assert chosen["attuned"] == ["wondrous.2", "wondrous.3"] and chosen["used"] == 3
    assert attunement(_kit(sheet), [], [])["attuned"] == []


def test_unattuned_armour_loses_its_refinement_and_says_so():
    sheet = _sheet()
    attuned = compile_character(sheet, actor_id=ME)
    plain = compile_character(sheet, actor_id=ME, attuned=[])
    assert plain["carrying"]["attunement"] == {"used": 0, "max": ATTUNEMENT_SLOTS, "attuned": []}
    assert attuned["carrying"]["attunement"]["attuned"] == ["treasure_armor"]
    assert plain["actor_template"]["armor_class"] == attuned["actor_template"]["armor_class"] - 1
    listing = equipment_list(sheet, attuned=[])
    armour = next(item for item in listing["items"] if item["key"] == "treasure_armor")
    assert armour["attunement_slots"] == 1 and not armour["attuned"] and listing["attunement"]["used"] == 0


def _service(tmp_path, monkeypatch, sheet):
    monkeypatch.setattr("factory_authoring.owner_items.OwnerItemStore.items", lambda self, project_id: [])
    service = TabletopService.__new__(TabletopService)
    service.buttons = ButtonStore(tmp_path / "buttons")
    service.combat = SimpleNamespace(userdata_root=tmp_path, _factory_owner_sheet=lambda project_id: sheet)
    monkeypatch.setattr(service, "sheet", lambda project_id: service.buttons.get(project_id))
    return service


def test_saving_attunement_checks_the_slots_and_keeps_the_choice(tmp_path, monkeypatch):
    project = "0b2d5c1e-4f7a-4a8e-9c3d-2e1f0a9b8c7d"
    service = _service(tmp_path, monkeypatch, _sheet(_wondrous("Hand Furnace", 0), _wondrous("Heavy Crown", 2), _wondrous("Lotus Ring", 1),
                                                     _wondrous("Jade Flute", 1)))
    with pytest.raises(TabletopError) as unknown:
        service.save_attunement(project, ["wondrous.0"])  # needs no attunement
    assert unknown.value.code == "TABLETOP_ATTUNEMENT_UNKNOWN"
    with pytest.raises(TabletopError) as full:
        service.save_attunement(project, ["treasure_armor", "wondrous.1", "wondrous.2", "wondrous.3"])  # 1 + 2 + 1 + 1
    assert full.value.code == "TABLETOP_ATTUNEMENT_FULL"
    assert service.save_attunement(project, ["wondrous.3", "wondrous.1", "wondrous.3"])["attuned"] == ["wondrous.1", "wondrous.3"]
    assert service.buttons.save(project, {}, set())["attuned"] == ["wondrous.1", "wondrous.3"]  # the other tables' saves keep it
    assert "attuned" not in service.save_attunement(project, None)  # back to the creation plan
