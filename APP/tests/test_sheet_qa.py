"""Owner-visible grant rows, causal choices, and read-only sheet QA."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from character_sheet.build_provenance import component_purpose, present_build_provenance
from character_sheet.current_rules import overlay_owner_current_rules
from combat.tabletop import sheet_library
from tools.sheet_qa import audit_character, browser_capture, library_entries, main


def fixture_sheet():
    rules = json.loads((Path(__file__).resolve().parents[1] / "authority/typed_mechanics/rules_text.json").read_text())
    ids = ["EQUIPMENT_BASE_ONE_FREE_EQUIPMENT_TALENT", "EQUIPMENT_BASE_FITTED_ARMOR_DESIGNATION"]
    components = [{"component_id": rid, "display_name": name, "player_rules_text": rules[rid]}
                  for rid, name in zip(ids, ["One free Equipment talent", "Fitted Armor designation"])]
    return {"identity": {"display_name": "Armor student"},
        "spheres_and_talents": {"automatic_sphere_components": components,
            "learned_talent_record_ids": ["chosen-talent"]},
        "selected_record_sections": {
            "spheres": [{"record_id": "sphere", "display_name": "Equipment"}],
            "sphere_automatic_components": [{"record_id": c["component_id"], "display_name": c["display_name"],
                "full_description": "Fitted Armor" if "DESIGNATION" in c["component_id"] else c["player_rules_text"],
                "parent_sphere_id": "sphere"} for c in components],
            "talents": [{"record_id": "chosen-talent", "display_name": "Reinforced Robes", "full_description": "Your robes protect you.", "parent_sphere_id": "sphere"}]}}


def test_owner_sheet_library_excludes_grant_keeps_concrete_choice_and_fitting_rule():
    sheet = fixture_sheet(); sealed = deepcopy(sheet)
    library = sheet_library(sheet, [], set())
    entries = {r.get("id"): r for _, r in library_entries(library)}
    assert "EQUIPMENT_BASE_ONE_FREE_EQUIPMENT_TALENT" not in entries
    assert "chosen-talent" in entries
    fitted = entries["EQUIPMENT_BASE_FITTED_ARMOR_DESIGNATION"]
    assert fitted["status"] == "info" and fitted["kind"] == "Equipment reference"
    assert "10 minutes" in fitted["text"] and "only one" in fitted["text"]
    assert sheet == sealed


def test_factory_overlay_retains_sealed_provenance_and_is_idempotent():
    sheet = fixture_sheet(); sealed = deepcopy(sheet)
    overlay = lambda s: overlay_owner_current_rules(s, edits={}, apply_owner_edit=lambda t,e: ([],t,[]),
        authenticated_rules_block=lambda s,r: ("", ""), factory_root=lambda: None)
    display = overlay(sheet)
    assert display["selected_record_sections"]["sphere_automatic_components"] == []
    assert display["build_provenance"]["grant_instructions"][0]["record_id"] == "EQUIPMENT_BASE_ONE_FREE_EQUIPMENT_TALENT"
    assert sheet == sealed and overlay(display) == display
    assert present_build_provenance(json.loads(json.dumps(display))) == display


def test_table_service_sheet_retains_fight_compilation_and_reload(tmp_path, monkeypatch):
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.test_shield_possession_and_armor import ROOT, AXE, HEAVY, SHIELD, _kit, _sheet
    sheet = _sheet(_kit(AXE, HEAVY, SHIELD), strength=16, dex=12)
    grant = fixture_sheet()
    sheet.setdefault("selected_record_sections", {})["sphere_automatic_components"] = grant["selected_record_sections"]["sphere_automatic_components"]
    sheet.setdefault("spheres_and_talents", {})["automatic_sphere_components"] = grant["spheres_and_talents"]["automatic_sphere_components"]
    sheet["spheres_and_talents"]["automatic_sphere_component_record_ids"] = [r["component_id"] for r in grant["spheres_and_talents"]["automatic_sphere_components"]]
    sheet["spheres_and_talents"]["sphere_record_ids"] = ["tianxia.sphere.equipment"]
    sealed = deepcopy(sheet)
    before = compile_character(sheet, actor_id="sheetqa:regression")
    display = present_build_provenance(sheet)
    assert compile_character(display, actor_id="sheetqa:regression") == before
    path = tmp_path / "sheet.json"; path.write_text(json.dumps(sheet))
    combat = CombatService(ROOT, tmp_path)
    monkeypatch.setattr(combat, "_factory_owner_sheet", lambda _pid: json.loads(path.read_text()))
    table = TabletopService(combat, tmp_path)
    project_id = "0badc0de-0000-4000-8000-000000000189"
    result = table.sheet(project_id)
    rows = {r.get("id"): r for _, r in library_entries(result["library"])}
    assert "EQUIPMENT_BASE_ONE_FREE_EQUIPMENT_TALENT" not in rows
    assert rows["EQUIPMENT_BASE_FITTED_ARMOR_DESIGNATION"]["status"] == "info"
    assert path.read_text() == json.dumps(sealed)
    assert TabletopService(combat, tmp_path).sheet(project_id)["library"] == result["library"]


@pytest.mark.parametrize("text,expected", [
    ("When you first gain the Example sphere, choose one Example talent and gain it for free.", "build"),
    ("When you learn Example, gain proficiency in one skill.", "build"),
    ("When you learn Example, gain Balanced Defense. While wielding two weapons, gain +1 AC.", "ability"),
    ("Action Type: Action\nChoose one creature. Gain one charge on a hit.", "ability"),
    ("Action Type: Bonus Action\nChoose one talent you know and apply it.", "ability"),
    ("While wearing armor, you gain resistance.", "ability"),
    ("When you learn this sphere, you learn this Meld automatically. Grant the target Darkvision. Augment - 2 CP: Increase its range.", "ability"),
    ("When you learn this sphere, you gain Bloodsense. You sense exposed blood within 60 feet.", "ability"),
    ("When you learn Sword, gain proficiency. If already proficient, gain +2 to attack rolls.", "ability"),
    ("Action Type: Passive\nTarget: Self\nWhen you gain this sphere, choose one talent and gain it for free.", "build"),
])
def test_generic_classifier_never_hides_runtime_or_mixed_rules(text, expected):
    assert component_purpose({"full_description": text}) == expected


def ledger():
    return {"spheres": [{"sphere_id": "sphere", "name": "Equipment", "gained_at_cl": 1}],
        "talents": [{"talent_id": "chosen-talent", "sphere": "Equipment", "gained_at_cl": 1, "acquisition_type": "new_sphere_bonus"}]}


def test_qa_requires_actual_owned_recorded_grant_not_any_same_sphere_talent():
    sheet = fixture_sheet(); library = sheet_library(sheet, [], set())
    assert not audit_character(sheet, ledger(), library)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = ["some-other-talent"]
    findings = audit_character(sheet, ledger(), library)
    assert [f["code"] for f in findings] == ["granted_talent_missing"]
    assert findings[0]["record_id"] == "chosen-talent"
    assert "proposal" in findings[0]
    missing = ledger(); missing["talents"] = []
    assert audit_character(sheet, missing, library)[0]["code"] == "unresolved_free_talent"
    wrong_route = ledger(); wrong_route["talents"][0]["acquisition_type"] = "background_talent"
    assert audit_character(sheet, wrong_route, library)[0]["code"] == "unresolved_free_talent"
    wrong_route["spheres"][0]["acquisition_type"] = "background_sphere"
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = ["chosen-talent"]
    assert not audit_character(sheet, wrong_route, library)


def test_qa_detects_original_screenshot_and_player_text_errors():
    sheet = fixture_sheet()
    legacy = {"groups": [{"key": "spheres", "entries": [
        {"id": c["component_id"], "name": c["display_name"], "text": c["player_rules_text"], "status": "gm"}
        for c in sheet["spheres_and_talents"]["automatic_sphere_components"]]}]}
    codes = [r["code"] for r in audit_character(sheet, ledger(), legacy)]
    assert "build_instruction_as_ability" in codes
    assert codes.count("misleading_not_automated_badge") == 2
    library = {"groups": [{"key": "test", "entries": [
        {"id": "a", "name": "**Factory Routing: TAL_EXAMPLE**", "text": "Same rules. " * 20},
        {"id": "b", "name": "Other", "text": "Same rules. " * 20}]}]}
    codes = {r["code"] for r in audit_character({}, {}, library)}
    assert {"raw_id_or_authoring_text", "raw_markdown", "duplicate_rules_text"} <= codes


def test_extra_grants_are_review_proposals_without_inventing_missing_choices():
    from tools.sheet_qa import additional_grant_findings
    sheet = {"spheres_and_talents": {"automatic_sphere_components": [{"component_id": "example",
        "player_rules_text": "When you learn this sphere, gain proficiency in one skill. You also gain a basic kit."}]}}
    [finding] = additional_grant_findings(sheet)
    assert finding["code"] == "additional_build_grant_review"
    assert "pre-acquisition" in finding["proposal"]
    assert sheet["spheres_and_talents"]["automatic_sphere_components"][0]["component_id"] == "example"


def test_cli_produces_per_character_reports_without_touching_inputs(tmp_path, monkeypatch):
    source = tmp_path / "inputs" / "character"; source.mkdir(parents=True)
    for name, value in [("Tianxia_Owner_Character_Sheet_v1.json", fixture_sheet()), ("Character_Master_Ledger.json", ledger())]:
        (source / name).write_text(json.dumps(value))
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    monkeypatch.setattr("tools.sheet_qa.table_library", lambda s: (s, sheet_library(s, [], set())))
    monkeypatch.delenv("SHEETQA_BROWSER", raising=False)
    assert main([str(source.parent), "--output", str(tmp_path / "report")]) == 0
    result = json.loads((tmp_path / "report/sheet-qa.json").read_text())
    assert result["characters"] == 1 and result["counts"] == {}
    assert result["reports"][0]["character_id"] == "character"
    assert (tmp_path / "report/sheet-qa.md").is_file()
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}


def test_browser_mode_does_not_import_or_launch_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("SHEETQA_BROWSER", raising=False)
    assert browser_capture(None, [], tmp_path).startswith("SKIPPED")


def test_generic_player_text_removes_build_identity_and_keeps_real_rules():
    from combat.player_text import clean
    text = "Record identity:\n  art id: tianxia.constructed.immortal_art.example\n  record source hash: abcdef\n\nAction Type: Action\nCanonical Action Type: Action\nFactory Combat Bucket: action\nSplit Candidate Buckets: action\nRange: 60 feet\nCost: 2 CP\nDeal 1d6 Fire damage."
    out = clean(text)
    assert "Record identity" not in out and "record source hash" not in out
    assert "tianxia.constructed" not in out and "Factory Combat Bucket" not in out
    assert "Split Candidate Buckets" not in out and "Canonical Action Type" not in out
    assert "60 feet" in out and "1d6 Fire damage" in out and "2 cultivation points" in out
    named = clean("Source rule: tianxia.path.qi_cultivation.feature.qi_armor. Cost: 2 CP.")
    assert "tianxia." not in named and "Qi Armor" in named and "2 cultivation points" in named


def test_actual_card_renderer_formats_rules_and_cleans_metadata_without_browser():
    import subprocess
    script = Path(__file__).resolve().parents[1] / "tools/sheet_qa_render.mjs"
    source = {"groups": [{"key": "test", "entries": [{"id": "x", "name": "Training", "status": "info",
        "text": "### Training\nFactory Routing: internal\nCost: None\nGain **proficiency**."}]}]}
    result = subprocess.run(["node", str(script)], input=json.dumps(source), text=True, capture_output=True, check=True)
    row = json.loads(result.stdout)["groups"][0]["entries"][0]
    assert "Factory Routing" not in row["text"] and "**" not in row["text"] and "###" not in row["text"]
    assert row["summary"] == "Gain proficiency."


@pytest.mark.skipif(os.environ.get("SHEETQA_BROWSER") != "1", reason="Lead runs Chromium outside sandbox")
def test_browser_sections_opt_in(tmp_path):
    url = os.environ.get("SHEETQA_BROWSER_URL")
    cid = os.environ.get("SHEETQA_CHARACTER_ID")
    if not url or not cid:
        pytest.skip("Set SHEETQA_BROWSER_URL template and SHEETQA_CHARACTER_ID")
    assert browser_capture(url, [{"character_id": cid}], tmp_path) == "CAPTURED"
    assert list(tmp_path.rglob("section-*.png"))
