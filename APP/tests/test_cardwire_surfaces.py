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
            "groups": {"Limits": ["Only when the triggering attack hits.",
                                 "Spend 1 CP (your Path resource) to add your PB to the roll."]}}
    for name, value in {
        "rules_text.json": {KEY: PRINTED, "synthetic.fallback": "### Fallback\nPrinted words."},
        "player_text.json": {"records": {KEY: TEXT, "synthetic.fallback": "Fallback\nClarified words."}},
        "owner_text_edits.json": {"records": {KEY: {"player_card": card}}},
        "record_sections.json": {},
    }.items():
        (data / name).write_text(json.dumps(value))
    monkeypatch.setattr(display_module, "DATA", data)
    monkeypatch.setattr(display_module, "SECTIONS", data / "record_sections.json")
    from combat import status_text
    monkeypatch.setattr(status_text, "RULES_TEXT_PATH", data / "rules_text.json")
    return display_module.record_display(KEY)


@pytest.mark.parametrize("surface", ["action", "setting", "augment", "shape", "bare_shape", "sheet", "reaction", "builder", "status"])
def test_every_surface_uses_one_record_projection(authority, surface, monkeypatch):
    from combat.action_text import layout_action
    from combat.option_text import CHOICE_LINE
    from combat.tabletop import engine_button_description, sheet_library
    row = {"display_name": "Sample", "parameters": {"typed": {"source": KEY}}}
    context = ""
    if surface in {"setting", "augment", "shape", "bare_shape"}:
        row.update({"economy": "NONE", "target_kind": "SELF", "costs": []})
        row["parameters"]["setting_only"] = True
        row["parameters"].update({"augment_key": KEY} if surface == "augment" else
                                 {"shape_talents": [KEY]} if surface == "shape" else {})
        if surface == "setting":
            row["parameters"].update(setting_description="Choose Sample for your next use.",
                                     description="This does not activate Sample.",
                                     setting_lifetime="Kept until changed.")
            context = ("Choose Sample for your next use.\n\nThis does not activate Sample.\n\n"
                       "Choosing this option takes no action and costs nothing. Kept until changed.")
        elif surface == "bare_shape":
            row["parameters"].update(zone_shape="sample", zone_name="Sample area")
            context = "Use Sample area without any optional area talents.\n\n" + CHOICE_LINE
        else:
            context = CHOICE_LINE
    if surface in {"action", "setting", "augment", "shape", "bare_shape"}:
        hover = layout_action(row)
        # Exact card equality applies only to rows with no button-owned text.
        reference = authority["text"].replace("1 CP (your Path resource)", "1 cultivation points (your Path resource)").replace(
            "your PB", "your Proficiency Bonus")
        reference += f"\n\nSource ability: {authority['title']}."
        expected = "\n\n".join(part for part in (reference, context) if part)
        assert engine_button_description(row) == hover["text"] == expected
        assert hover["context"] == context
        if surface != "action":
            assert hover["text"].count("Choosing this option takes no action and costs nothing") == 1
            if surface != "setting":
                assert hover["text"].endswith(CHOICE_LINE)
        if surface in {"setting", "bare_shape"}:
            from combat.tabletop import setting_button_description
            assert setting_button_description(row, {}) == expected
        if surface == "setting":
            from combat.tabletop import untyped_button_text
            monkeypatch.setattr("combat.tabletop._toggle_owner", lambda *args, **kwargs: KEY)
            text = untyped_button_text({"display_name": "Sample: Choice", "parameters": {}}, {})
            assert text.endswith("Source ability: Sample.")
    elif surface == "sheet":
        library = sheet_library({"selected_record_sections": {"talents": [
            {"record_id": KEY, "display_name": "Sample", "full_description": PRINTED}]}}, [], set())
        item = next(item for group in library["groups"] for sphere in group.get("spheres", [])
                    for item in sphere["entries"])
        assert item["text"] == authority["text"]
        return
    elif surface == "builder":
        from factory_authoring.record_display import present_records
        choices = present_records({"categories": [{"choices": [
            {"choice_id": KEY}, {"choice_id": "synthetic.missing", "short_description": TEXT},
        ]}]})["categories"][0]["choices"]
        assert choices[1]["player_card"] == display_module.record_display("", fallback=TEXT)
        assert "Gain 5 Temporary Hit Points." in choices[1]["player_card"]["text"]
        hover = {"player_card": choices[0]["player_card"]}
    elif surface == "status":
        from combat import ext, status_text
        monkeypatch.setattr(ext, "query", lambda *args: [
            {"text": authority["text"], "player_card": authority}, {"text": "Duplicated raw parent."}])
        owner = SimpleNamespace(entity_id="mei")
        action = SimpleNamespace(owner_id="mei", parameters={"typed": {"source": KEY}}, costs=())
        engine = SimpleNamespace(action_catalog={"source": action, "reader": action},
                                 state=SimpleNamespace(actors={"mei": owner}))
        result = status_text.describe(engine, owner, {"condition_id": "condition:typed.mark.sample.mei",
            "display_name": "Sample mark", "source_definition_id": "source",
            "source_actor_id": "mei", "expires_on": "UNTIL_REMOVED"}, {"record": KEY},
            {"mei": "Mei"}, {"source": "Sample", "reader": "Spend Sample"},
            mark_readings={"sample": "The next hit consumes this mark."})
        hover = result["hover"]
        for text in (result["rule_text"], result["detail"]):
            assert "cultivation points" in text and "Proficiency Bonus" in text
            assert "1 CP" not in text and "your PB" not in text
            assert "The next hit consumes this mark." in text
            assert "Duplicated raw parent." not in text
        assert hover["duration"] == result["duration"] == "until removed"
        assert hover["footer"] == "Applied by Mei, from Sample. Lasts until removed."
        for text in (result["detail"], hover["context"]):
            assert hover["footer"] in text
            assert "The next hit consumes this mark." in text
            assert "Used by: Spend Sample." in text
        assert result["detail"].count("Gain 5 Temporary Hit Points.") == 1
        assert result["detail"].count("Spend Sample") == 1  # named readers are not repeated as prose
    else:
        # Reaction rows consume the same library hover as their source entry.
        hover = layout_action({"label": "Sample", "parameters": {"typed": {"source": KEY}}})
    assert hover["player_card"] == authority
    result = subprocess.run(["node", str(APP / "tests/cardwire_surfaces.mjs"), surface],
                            input=json.dumps({"hover": hover, "detail": result["detail"]} if surface == "status" else hover),
                            text=True, capture_output=True, cwd=APP)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("variant,costs,total,own", [
    (False, [("resource:path.qi", 3)], "3 Qi", ""),
    (True, [("resource:path.qi", 3)], "3 Qi", ""),
    (True, [("resource:path.qi", 2), ("resource:path.qi", 1)], "2 Qi, 1 Qi", ""),
    (True, [("resource:path.qi", 3)], "3 Qi", "replacement"),
    (True, [("resource:path.qi", 3)], "3 Qi", "explicit"),
])
def test_carded_button_keeps_live_charge_and_usage(authority, variant, costs, total, own):
    from combat.tabletop import engine_button_description, engine_button_layout, auto_buttons
    row = {"source_definition_id": "action:typed.sample", "display_name": "Sample + Extra" if variant else "Sample",
           "economy": "REACTION", "target_kind": "SELF", "costs": costs,
           "parameters": {"typed": {"source": KEY, "once": "round",
               **({"variant_of": "base", "modifier": {"name": "Extra"}} if variant else {})}}}
    if own:
        # Real hook metadata, not a stub: a card must not swallow the removed save.
        row["parameters"]["typed"]["replacement"] = {
            "base_name": "Sample", "removed": [{"type": "save", "ability": "CON"}],
            "reliable": [{"type": "mark", "mark": "Dose Mark"}]}
    if own == "explicit":
        row["parameters"]["description"] = "Use the saved instructions instead.\nCost: 2 Qi"
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
        slot_note = "Extra rides on Sample: together they spend your Reaction."
        assert slot_note in hover["text"] and slot_note in hover["context"]
    if own == "explicit":
        assert hover["text"].startswith("Use the saved instructions instead.")
        assert "Use the saved instructions instead." in hover["context"]
        assert "The target is never asked to make that save." not in hover["text"]
    elif own == "replacement":
        explanation = "The target is never asked to make that save."
        assert explanation in hover["context"] and explanation in hover["text"]
        assert "a hit always gives the target 1 Dose Mark." in hover["text"]
    result = subprocess.run(["node", str(APP / "tests/cardwire_surfaces.mjs"), "live"],
                            input=json.dumps(hover), text=True, capture_output=True, cwd=APP)
    assert result.returncode == 0, result.stdout + result.stderr


def test_offline_rule_presentations():
    # Keep the existing plain-text/disclosure assertions runnable without the
    # private roster wrapper; only the shipped public Node fixtures are used.
    result = subprocess.run(["node", "--test", "tests/n2_rules.test.mjs",
                             "static/tabletop/presentation.test.mjs"],
                            text=True, capture_output=True, cwd=APP, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_uncarded_record_keeps_clarified_text_and_collapsed_printed_rules(authority):
    display = display_module.record_display("synthetic.fallback")
    assert display["text"] == "Clarified words."
    assert "Printed words." in display["html"]
    assert "<details><summary>Rules</summary>" in display["html"]
