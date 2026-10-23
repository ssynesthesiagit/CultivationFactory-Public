"""Current rules outrank acquisition receipts through the real Table sheet service."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from character_sheet.build_provenance import present_build_provenance
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_shield_possession_and_armor import ROOT, AXE, HEAVY, SHIELD, _kit, _sheet
from tests.test_sheet_talent_rules_text import _service
from tools.sheet_qa import LEDGER, SHEET, audit_character, library_entries, main


@pytest.mark.parametrize("origin", ["owner-edit", "authenticated", "owner-edit-title-only"])
@pytest.mark.parametrize("reference", [False, True], ids=["ongoing-grant", "shorter-reference"])
def test_effective_rules_survive_service_repeat_and_cold_reload(tmp_path, monkeypatch, origin, reference):
    authenticated = origin == "authenticated"
    record_id = "sheetqa-current-rules"
    name = "Fitted Armor designation" if reference else "Example training"
    if reference:
        receipt = "### Fitted Armor\nDuring a long rest, or by spending 10 minutes with proficient armor, designate your Fitted Armor."
        current = "By spending 5 minutes with proficient armor, designate your Fitted Armor."
    else:
        receipt = "When you learn Example, gain proficiency in one skill."
        current = receipt + " If already proficient, gain +2 to relevant checks."
    sheet = _sheet(_kit(AXE, HEAVY, SHIELD), strength=16, dex=12)
    sheet.setdefault("spheres_and_talents", {})["automatic_sphere_components"] = [
        {"component_id": record_id, "display_name": name, "player_rules_text": receipt}]
    sheet["spheres_and_talents"]["automatic_sphere_component_record_ids"] = [record_id]
    card = {"record_id": record_id, "display_name": name,
            "full_description": current if authenticated else receipt,
            "record_hash": "sealed-record-hash"}
    if origin == "owner-edit-title-only":
        card["full_description"] = "### Fitted Armor" if reference else name
    if authenticated:
        card.update(full_description_source="locked_catalog_record_rules_text",
                    rules_text_source_locator="authenticated.md::line:1")
    sheet.setdefault("selected_record_sections", {})["sphere_automatic_components"] = [card]
    path = tmp_path / "sheet.json"
    path.write_text(json.dumps(sheet))
    sealed_bytes = path.read_bytes()
    # Substitute only owner-edit file I/O, using the real overlay/apply_edit.
    edits_path = ROOT / "authority/typed_mechanics/owner_text_edits.json"
    read_text = Path.read_text
    edits = {} if authenticated else {record_id: {"replace": [{"old": receipt, "new": current}]}}
    monkeypatch.setattr(Path, "read_text", lambda p, *a, **kw:
                        json.dumps({"records": edits}) if p == edits_path else read_text(p, *a, **kw))
    expected_source = "locked_catalog_record_rules_text" if authenticated else "Owner-edited current rules"
    first = None
    for _ in range(2):
        combat = CombatService(ROOT, tmp_path)
        monkeypatch.setattr(combat, "_factory_owner_sheet", lambda _pid: json.loads(path.read_text()))
        table = TabletopService(combat, tmp_path)
        pid = "0badc0de-0000-4000-8000-000000000189"
        result = table.sheet(pid)
        entries = {r.get("id"): r for _, r in library_entries(result["library"])}
        assert record_id in entries
        assert current == entries[record_id]["text"]
        assert entries[record_id]["kind"] == ("Equipment reference" if reference else "Base ability")
        assert entries[record_id]["status"] == ("info" if reference else "gm")
        display, _, _ = table._bundle_and_summary(pid)
        section = "equipment_reference" if reference else "sphere_automatic_components"
        [row] = display["selected_record_sections"][section]
        assert row["full_description"] == current
        assert row["full_description_source"] == expected_source
        assert row["record_hash"] == "sealed-record-hash"
        assert present_build_provenance(deepcopy(display)) == display
        # A repeated Factory overlay must not replace shorter authenticated or
        # owner-edited prose with a longer, superseded source block either.
        service = _service(ROOT)
        monkeypatch.setattr(service, "_authenticated_rules_block", lambda _s, _r: (receipt, "old.md::line:1"))
        assert service._with_authenticated_rules_text(deepcopy(display)) == display
        if first is not None:
            assert result["library"] == first
        first = result["library"]
    assert path.read_bytes() == sealed_bytes
    # Audit the actual service/current-rule result through the CLI. Receipts
    # remain historical even when the owner adds a legitimate ongoing benefit.
    source = tmp_path / "inputs" / "character"
    source.mkdir(parents=True)
    (source / SHEET).write_bytes(sealed_bytes)
    (source / LEDGER).write_text(json.dumps({}))
    input_bytes = {p.name: p.read_bytes() for p in source.iterdir()}
    monkeypatch.delenv("SHEETQA_BROWSER", raising=False)
    output = tmp_path / "audit"
    assert main([str(source.parent), "--output", str(output)],
                render_sheet=lambda _sheet: (display, result["library"])) == 0
    report = json.loads((output / "sheet-qa.json").read_text())
    findings = report["reports"][0]["findings"]
    codes = {f["code"] for f in findings if f.get("record_id") == record_id}
    assert "build_instruction_as_ability" not in codes
    assert "misleading_not_automated_badge" not in codes
    if not reference:
        assert "additional_build_grant_review" in codes
        assert "mixed_grant_requires_review" in codes
    assert "render_error" not in report["counts"]
    assert input_bytes == {p.name: p.read_bytes() for p in source.iterdir()}


@pytest.mark.parametrize("text,source,expected", [
    ("", None, "receipt"),
    ("### Training", None, "receipt"),
    ("Action Type: Passive\nTarget: Self", None, "receipt"),
    ("Gain +2 to checks.", None, "current"),
    ("### Training", "Owner-edited current rules", "current"),
    ("", "locked_catalog_record_rules_text", "current"),
])
def test_receipt_fallback_requires_missing_unauthenticated_rules(text, source, expected):
    from character_sheet.build_provenance import effective_component_rules
    receipt = {"player_rules_text": "### Training\nWhen you learn Example, gain proficiency in one skill."}
    row = {"display_name": "Training", "full_description": text,
           "full_description_source": source}
    sealed = deepcopy(row)
    result = effective_component_rules(row, receipt)
    assert result["full_description"] == (receipt["player_rules_text"] if expected == "receipt" else text)
    assert row == sealed


@pytest.mark.parametrize("with_display", [False, True])
def test_audit_current_bonus_keeps_historical_grant_evidence_separate(with_display):
    receipt = "When you learn Example, gain proficiency in one skill."
    current = "If already proficient, gain +2 to relevant checks."
    sheet = {"spheres_and_talents": {"automatic_sphere_components": [
        {"component_id": "training", "player_rules_text": receipt}]}}
    display = {"selected_record_sections": {"sphere_automatic_components": [
        {"record_id": "training", "display_name": "Example training",
         "full_description": current, "player_rules_text": receipt}]}}
    library = {"groups": [{"key": "spheres", "entries": [
        {"id": "training", "name": "Example training", "text": current, "status": "gm"}]}]}
    sealed = deepcopy((sheet, display, library))
    findings = audit_character(sheet, {}, library, display=display if with_display else None)
    # A removed acquisition sentence cannot be diagnosed as currently visible.
    assert [f["code"] for f in findings] == ["additional_build_grant_review"]
    assert (sheet, display, library) == sealed
