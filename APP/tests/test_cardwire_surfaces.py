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


@pytest.mark.parametrize("variant,costs,total", [
    (False, [("resource:path.qi", 3)], "3 Qi"),
    (True, [("resource:path.qi", 3)], "3 Qi"),
    (True, [("resource:path.qi", 2), ("resource:path.qi", 1)], "2 Qi, 1 Qi"),
])
def test_carded_button_keeps_live_charge_and_usage(authority, variant, costs, total):
    from combat.tabletop import engine_button_description, engine_button_layout, auto_buttons
    row = {"source_definition_id": "action:typed.sample", "display_name": "Sample + Extra" if variant else "Sample",
           "economy": "REACTION", "target_kind": "SELF", "costs": costs,
           "parameters": {"typed": {"source": KEY, "once": "round",
               **({"variant_of": "base", "modifier": {"name": "Extra"}} if variant else {})}}}
    hover = engine_button_layout(row)
    button = next(b for b in auto_buttons({"action_catalog": [row]}, {}) if b["id"] == "act:action:typed.sample")
    assert hover["player_card"] == authority  # the cached reference card is not mutated
    assert hover["text"] == engine_button_description(row) == button["description"]
    assert "Once per round: available again at the start of the next round." in hover["text"]
    assert "Once per round" in hover["context"]
    if len(costs) == 1:
        assert "Cost: 3 Qi" in hover["text"] and "Cost: 2 Qi" not in hover["text"]
    if variant:
        assert f"This version costs {total} in total." in hover["text"]
    result = subprocess.run(["node", str(APP / "tests/cardwire_surfaces.mjs"), "live"],
                            input=json.dumps(hover), text=True, capture_output=True, cwd=APP)
    assert result.returncode == 0, result.stdout + result.stderr


def test_uncarded_record_keeps_clarified_text_and_collapsed_printed_rules(authority):
    display = display_module.record_display("synthetic.fallback")
    assert display["text"] == "Clarified words."
    assert "Printed words." in display["html"]
    assert "<details><summary>Rules</summary>" in display["html"]
