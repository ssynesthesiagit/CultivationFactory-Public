"""Armor Dexterity caps stay faithful to every printed catalog formula."""
import re

from combat.armour import armor_class
from factory_authoring.starting_kits import _authorities
from tests.test_attack_abilities import ROOT, sheet, table_fixture
from combat.gate5_service import CombatService

WEAPON = "tianxia.mortal.weapon.jian"
ARMOR = "tianxia.mortal.armor.lacquered_lamellar"


def test_every_catalog_armor_uses_its_printed_dexterity_cap():
    catalog = _authorities()[1]
    armors = [(item_id, row) for item_id, row in catalog.items() if row.get("armor_category")]
    assert armors
    for item_id, chassis in armors:
        formula = str(chassis.get("armor_class") or "")
        if str(chassis.get("armor_category")).lower() == "shield":
            expected = 12  # base AC 10 plus the catalog's separate +2 shield bonus
        else:
            match = re.match(r"^\s*(\d+)", formula)
            assert match, f"{chassis.get('name')}: unrecognized armor formula {formula!r}"
            dex = 4 if "dex modifier" in formula.lower() else 0
            cap = re.search(r"\(\s*max\s*\+?(\d+)\s*\)", formula, re.I)
            if cap:
                dex = min(dex, int(cap.group(1)))
            expected = max(10, int(match.group(1)) + dex)
        actual = armor_class(10, {"resolved_treasure_armor": {"chassis": chassis}}, {"DEX": 4})
        assert actual == expected, f"{chassis.get('name')} ({item_id}, {formula}): expected AC {expected}, got {actual}"


def test_refined_lamellar_caps_dex_on_a_committed_tabletop_attack(tmp_path):
    owner = sheet(strength=18, dexterity=18, training=False)
    owner["equipment"] = [{"starting_kit": {
        "items": [{"item_id": WEAPON, "quantity": 1}],
        "resolved_treasure_armor": {
            "name": "Refined Lamellar", "chassis": _authorities()[1][ARMOR],
            "refinement_bonus": 2, "enhancements": [],
        },
    }}]
    combat, table, match, actor, foe = table_fixture(tmp_path, owner)
    state = table.state(match)
    group = next(group for group in state["menu"]["actions"] if ".weapon.jian" in group["source_definition_id"])
    option = next(option for option in group["options"] if foe in option["target_ids"])
    response = table.act(match, option["candidate_id"], state["menu"]["decision_id"],
                         state["menu"]["state_version"], state["last_sequence"], [])
    assert response["status"] == "COMMITTED"
    current = combat._load_session(match)
    assert current.engine.state.actors[actor].armor_class == 18  # 14 + min(4, 2) + refinement 2
    fresh = CombatService(ROOT, tmp_path)._load_session(match)
    assert fresh.engine.state.model_dump(mode="json") == current.engine.state.model_dump(mode="json")
    verify = fresh.verify()
    replay = fresh.mechanical.replay()
    assert verify["status"] == replay["status"] == "PASS"
    assert verify["canonical_state_sha256"] == replay["canonical_state_sha256"]
