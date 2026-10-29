"""Relevant-only: one record projection across the shipped display boundaries."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from factory_authoring import record_display as display_module
from factory_authoring.player_rules import card_sha

APP = Path(__file__).resolve().parents[1]
KEY = "synthetic.card"
PRINTED = "### Sample\nAction Type: Reaction\nCost: 2 Qi\nGain 5 Temporary Hit Points."
TEXT = "Sample\nAction: Reaction\nCost: 2 Qi\nGain 5 Temporary Hit Points."


@pytest.fixture
def authority(tmp_path, monkeypatch):
    data = tmp_path / "display"
    data.mkdir()
    card = {"source_sha256": card_sha(TEXT), "rules_sha256": card_sha(PRINTED),
            "summary": "Gain 5 Temporary Hit Points.", "facts": [["Action", "Reaction"], ["Cost", "2 Qi"]],
            "groups": {"Limits": ["Only when the triggering attack hits."]}}
    for name, value in {
        "rules_text.json": {KEY: PRINTED, "synthetic.fallback": "### Fallback\nPrinted words."},
        "player_text.json": {"records": {KEY: TEXT, "synthetic.fallback": "Fallback\nClarified words."}},
        "owner_text_edits.json": {"records": {KEY: {"player_card": card}}},
    }.items():
        (data / name).write_text(json.dumps(value))
    monkeypatch.setattr(display_module, "DATA", data)
    from combat import status_text
    monkeypatch.setattr(status_text, "RULES_TEXT_PATH", data / "rules_text.json")
    return display_module.record_display(KEY)


@pytest.mark.parametrize("surface", ["action", "setting", "augment", "shape", "sheet", "reaction", "builder", "status"])
def test_every_surface_uses_one_record_projection(authority, surface, monkeypatch):
    from combat.action_text import layout_action
    from combat.tabletop import engine_button_description, sheet_library
    row = {"display_name": "Sample", "parameters": {"typed": {"source": KEY}}}
    if surface in {"setting", "augment", "shape"}:
        row.update({"economy": "NONE", "target_kind": "SELF", "costs": []})
        row["parameters"]["setting_only"] = True
        row["parameters"].update({"augment_key": KEY} if surface == "augment" else
                                 {"shape_talents": [KEY]} if surface == "shape" else {})
    if surface in {"action", "setting", "augment", "shape"}:
        hover = layout_action(row)
        assert engine_button_description(row) == authority["text"]
    elif surface == "sheet":
        library = sheet_library({"selected_record_sections": {"talents": [
            {"record_id": KEY, "display_name": "Sample", "full_description": PRINTED}]}}, [], set())
        item = next(item for group in library["groups"] for sphere in group.get("spheres", [])
                    for item in sphere["entries"])
        assert item["text"] == authority["text"]
        return
    elif surface == "builder":
        from factory_authoring.record_display import present_records
        item = present_records({"categories": [{"choices": [{"choice_id": KEY}]}]})["categories"][0]["choices"][0]
        hover = {"player_card": item["player_card"]}
    elif surface == "status":
        from combat import ext, status_text
        monkeypatch.setattr(ext, "query", lambda *args: [
            {"text": "Duplicated raw parent."}, {"rules": "Another raw parent reading."}])
        engine = SimpleNamespace(action_catalog={}, state=SimpleNamespace(actors={}))
        result = status_text.describe(engine, None, {"condition_id": "condition:typed.sample",
            "display_name": "Sample"}, {"record": KEY}, {}, {})
        hover = result["hover"]
        assert result["detail"] == authority["text"]
    else:
        # Reaction rows consume the same library hover as their source entry.
        hover = layout_action({"label": "Sample", "parameters": {"typed": {"source": KEY}}})
    assert hover["player_card"] == authority
    result = subprocess.run(["node", str(APP / "tests/cardwire_surfaces.mjs"), surface],
                            input=json.dumps(hover), text=True, capture_output=True, cwd=APP)
    assert result.returncode == 0, result.stdout + result.stderr


def test_uncarded_record_keeps_clarified_text_and_collapsed_printed_rules(authority):
    display = display_module.record_display("synthetic.fallback")
    assert display["text"] == "Clarified words."
    assert "Printed words." in display["html"]
    assert "<details><summary>Rules</summary>" in display["html"]
