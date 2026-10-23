"""Printed mixed rules survive the real sheet service, including a cold reload."""
from copy import deepcopy
import json

import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_shield_possession_and_armor import ROOT, AXE, HEAVY, SHIELD, _kit, _sheet
from tools.sheet_qa import library_entries


@pytest.mark.parametrize("record_id,phrases", [
    ("SECT_STEWARDSHIP_BASE_LEARNING_SECT_STEWARDSHIP", ["+2 bonus to checks", "chosen skill or tool", "institutional logistics"]),
    ("SWORD_BASE_SWORD_PRACTICE", ["Body Refiner", "only through", "use Stamina instead of cultivation points"]),
    ("TAL_FLOWERS_FRAGRANT_VEIL", ["Lightly Obscured", "Disadvantage", "sight or smell"]),
    ("TAL_MAGMA_MAGMA_INITIATION", ["fade when the talent ends", "lasting obsidian"]),
])
def test_printed_mixed_rule_survives_sheet_service_and_reload(tmp_path, monkeypatch, record_id, phrases):
    rules = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    sheet = _sheet(_kit(AXE, HEAVY, SHIELD), strength=16, dex=12)
    name = rules[record_id].splitlines()[0].lstrip("# ")
    sheet.setdefault("spheres_and_talents", {})["automatic_sphere_components"] = [
        {"component_id": record_id, "display_name": name, "player_rules_text": rules[record_id]}]
    sheet["spheres_and_talents"]["automatic_sphere_component_record_ids"] = [record_id]
    sheet.setdefault("selected_record_sections", {})["sphere_automatic_components"] = [
        {"record_id": record_id, "display_name": name, "full_description": rules[record_id]}]
    sealed = deepcopy(sheet)
    path = tmp_path / "sheet.json"
    path.write_text(json.dumps(sheet))
    for _ in range(2):
        combat = CombatService(ROOT, tmp_path)
        monkeypatch.setattr(combat, "_factory_owner_sheet", lambda _pid: json.loads(path.read_text()))
        result = TabletopService(combat, tmp_path).sheet("0badc0de-0000-4000-8000-000000000189")
        entries = {r.get("id"): r for _, r in library_entries(result["library"])}
        assert record_id in entries
        for phrase in phrases:
            assert phrase in entries[record_id]["text"]
    assert json.loads(path.read_text()) == sealed


@pytest.mark.parametrize("tail", [
    "If already proficient, gain +2 to relevant checks.",
    "Spend Stamina instead of CP for projected techniques.",
    "A practitioner may learn the projected form only through an explicit feature.",
    "Creatures in the area have Disadvantage on sight checks.",
    "An unfamiliar ongoing rule must remain visible.",
])
def test_unrecognized_remainder_is_not_proof_of_pure_acquisition(tail):
    from character_sheet.build_provenance import component_purpose
    assert component_purpose({"full_description": "When you learn Example, gain proficiency in one skill. " + tail}) == "ability"
