"""Table-level checks for printed weapon hand requirements."""
import pytest

from combat.gate5_service import CombatService
from tests.test_attack_abilities import ROOT, sheet, table_fixture

WEAPON = "tianxia.mortal.weapon."
SHIELD = "tianxia.mortal.armor.shield"


def _equipment_fixture(tmp_path, weapon, *, shield):
    owner = sheet(strength=18, dexterity=18, training=False)
    owner["equipment"] = [{"starting_kit": {"items": [
        {"item_id": WEAPON + weapon, "quantity": 1},
        *([{"item_id": SHIELD, "quantity": 1}] if shield else []),
    ]}}]
    return table_fixture(tmp_path, owner)


def _round_trip(combat, match, tmp_path):
    current = combat._load_session(match)
    fresh = CombatService(ROOT, tmp_path)._load_session(match)
    assert fresh.engine.state.model_dump(mode="json") == current.engine.state.model_dump(mode="json")
    verify = fresh.verify()
    replay = fresh.mechanical.replay()
    assert verify["status"] == replay["status"] == "PASS"
    assert verify["canonical_state_sha256"] == replay["canonical_state_sha256"]


@pytest.mark.parametrize("weapon", ["qiang", "gong_jian"])
def test_shield_hides_two_handed_weapon_attack_from_table_menu(tmp_path, weapon):
    combat, table, match, actor, _ = _equipment_fixture(tmp_path, weapon, shield=True)
    state = table.state(match)
    actions = [group for group in state["menu"]["actions"]
               if f".weapon.{weapon}" in group["source_definition_id"]]
    assert not actions, "a shield occupies one hand, so a two-handed attack is not a legal table action"
    _round_trip(combat, match, tmp_path)


def test_two_handed_weapon_remains_available_without_a_shield(tmp_path):
    combat, table, match, actor, _ = _equipment_fixture(tmp_path, "qiang", shield=False)
    state = table.state(match)
    assert any(".weapon.qiang" in group["source_definition_id"] for group in state["menu"]["actions"])
    _round_trip(combat, match, tmp_path)


def test_shield_uses_one_handed_versatile_damage_on_table_attack(tmp_path):
    combat, table, match, actor, foe = _equipment_fixture(tmp_path, "jian", shield=True)
    state = table.state(match)
    group = next(group for group in state["menu"]["actions"] if ".weapon.jian" in group["source_definition_id"])
    option = next(option for option in group["options"] if foe in option["target_ids"])
    result = table.act(match, option["candidate_id"], state["menu"]["decision_id"],
                       state["menu"]["state_version"], state["last_sequence"], [])
    assert result["status"] == "COMMITTED"
    action = next(action for action in combat._load_session(match).engine.action_catalog.values()
                  if action.source_definition_id.endswith(".weapon.jian"))
    assert action.parameters["typed"]["weapon"]["damage"]["sides"] == 8
    _round_trip(combat, match, tmp_path)
