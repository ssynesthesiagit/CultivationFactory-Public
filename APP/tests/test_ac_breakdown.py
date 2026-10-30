"""SOL191: display provenance reaches the real sheet/table API, without changing AC."""
import json
from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_armor_class_consumers import _install_sheet
from tests.test_sheet_worn_armour_matches_fight import _heavy_and_shield

ROOT = Path(__file__).resolve().parents[1]


def scratch_sheet_payload(tmp_path):
    """Compile the existing real-character fixture through the production sheet API."""
    sheet = json.loads((ROOT / "tests/fixtures/gm_sheet/scratch_owner_sheet_snapshot.fixture.json").read_text())
    _install_sheet(tmp_path, sheet, "abcdef19")
    return TabletopService(CombatService(ROOT, tmp_path), tmp_path).sheet("abcdef19")


def test_real_sheet_api_keeps_formula_and_conditional_bonus(tmp_path):
    payload = scratch_sheet_payload(tmp_path)
    ac = payload["summary"]["armor_breakdown"]
    assert ac["formula_trace"]["root"]["value"] == 12
    assert "Qi Armor" in ac["conditional_note"]
    assert ac["effective_value"] == payload["summary"]["armor_class"]
    assert sum(row["value"] for row in ac["combat_terms"]) == ac["effective_value"]


def test_equipment_breakdown_uses_the_compiler_calculation(tmp_path):
    sheet = _heavy_and_shield(strength=10)
    _install_sheet(tmp_path, sheet, "abcdef20")
    payload = TabletopService(CombatService(ROOT, tmp_path), tmp_path).sheet("abcdef20")
    terms = payload["summary"]["armor_breakdown"]["combat_terms"]
    assert {row["source"]: row["value"] for row in terms} == {"Imperial Plate Battle Dress": 18, "shield": 2}
    assert sum(row["value"] for row in terms) == payload["summary"]["armor_class"] == 20
    bundle = compile_character(sheet, actor_id="actor:ac")
    assert bundle["actor_template"]["armor_class"] == 20


def test_live_ac_projection_survives_table_commit_reload(tmp_path):
    from tests.test_shield_possession_and_armor import ME, _bundle, _kit, _sheet, HEAVY, AXE, SHIELD, _table_match, _table_do

    combat, table, match = _table_match(tmp_path, _bundle(_sheet(_kit(HEAVY, AXE, SHIELD), base_ac=10, strength=14)))
    assert _table_do(table, match, "Drop Shield")["status"] == "COMMITTED"
    fresh = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    for service in (table, fresh):
        row = next(row for row in service.state(match)["presentation"]["actors"] if row["entity_id"] == ME)
        assert row["armor_base"] == 20
        assert next(d["value"] for d in row["defenses"] if d["defense_id"] == "defense:armor_class") == 18
        assert isinstance(row["armor_modifiers"], list)
    assert fresh.combat._load_session(match).mechanical.replay()["status"] == "PASS"


def test_armor_dexterity_cap_terms_and_no_result_change():
    from combat import armour
    from tests.test_shield_possession_and_armor import _kit, LIGHT

    terms = []
    kit = _kit(LIGHT)
    value = armour.armor_class(10, kit, {"DEX": 3}, breakdown=terms)
    assert value == armour.armor_class(10, kit, {"DEX": 3})
    assert sum(row["value"] for row in terms) == value
    assert next(row["value"] for row in terms if row["source"] == "Dexterity modifier") == 3
    terms = []
    kit = {"resolved_treasure_armor": {"chassis": {"name": "Medium armor", "armor_category": "medium",
                                                   "armor_class": "14 + Dex modifier (max +2)"}}}
    value = armour.armor_class(10, kit, {"DEX": 4}, breakdown=terms)
    assert value == armour.armor_class(10, kit, {"DEX": 4}) == 16
    assert terms == [{"source": "Medium armor", "value": 14},
                     {"source": "Dexterity modifier (armor caps the bonus at +2)", "value": 2}]
