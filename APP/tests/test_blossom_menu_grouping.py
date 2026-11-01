"""Blossom pickers are grouped under Cultivate Blossom, and their tooltip states the CP cost once.

Owner 2026-10-12 (BLOSSOMMENU): "Blossom: Medicinal Blossom (1 CP)" showed as a top-level row, and its tooltip said
"This button picks: ..." twice with the cost in brackets. The picker carries its ability as `parent` on the sheet and
table buttons, and the choice text reads "1 CP (cultivation points, your Path resource)" once on both the plain and
the structured (markup) paths.
"""
from combat.ext import blossom
from combat.option_text import setting_text
from combat.tabletop import auto_buttons
from tests.h48_table_support import OWNER, fixture


def _owner_actions(tmp_path):
    _, table, match_id, _, _ = fixture(tmp_path, [blossom.THORN], seed="blossommenu")
    engine = table.combat._load_session(match_id).engine
    return [a for a in engine.action_catalog.values() if a.owner_id == OWNER]


def _pick(actions, suffix):
    return next(a for a in actions if a.source_definition_id.endswith(suffix))


def test_pickers_name_their_ability_as_parent_on_the_sheet(tmp_path):
    actions = _owner_actions(tmp_path)
    parent = _pick(actions, "blossom.cultivate").source_definition_id
    bundle = {"action_catalog": [a.model_dump(mode="json") for a in actions]}
    buttons = {b["combat"]["source_definition_id"]: b for b in auto_buttons(bundle, {"cultivation_level": 17}) if (b.get("combat") or {}).get("source_definition_id")}
    assert buttons[_pick(actions, "blossom.pick.medicinal").source_definition_id]["parent"] == parent
    assert buttons[_pick(actions, "blossom.pick.thorned").source_definition_id]["parent"] == parent
    assert "parent" not in buttons[parent]


def test_live_table_menu_pickers_carry_their_parent(tmp_path):
    _, table, match_id, _, _ = fixture(tmp_path, [blossom.THORN], seed="blossommenu")
    menu = table.state(match_id)["menu"]
    actions = [a for a in table.combat._load_session(match_id).engine.action_catalog.values() if a.owner_id == OWNER]
    parent = _pick(actions, "blossom.cultivate").source_definition_id
    pickers = [a for a in menu["actions"] if a["source_definition_id"].endswith(("blossom.pick.medicinal", "blossom.pick.thorned"))]
    assert len(pickers) == 2
    assert {a["parent"] for a in pickers} == {parent}


def test_choice_text_states_cost_once_on_plain_and_structured_paths(tmp_path):
    row = _pick(_owner_actions(tmp_path), "blossom.pick.medicinal").model_dump(mode="json")
    description = str(row["parameters"].get("description") or "")
    for with_markup in (False, True):
        text = setting_text(row, description, with_markup=with_markup)
        assert text.count("your Path resource") == 1
        assert "1 CP (cultivation points, your Path resource)" in text
        assert text.count("This button picks:") == 1


def test_pickers_are_listed_in_the_ability_options_panel_not_the_bar(tmp_path):
    _, table, match_id, _, _ = fixture(tmp_path, [blossom.THORN], seed="blossommenu")
    state = table.state(match_id)
    actions = [a for a in table.combat._load_session(match_id).engine.action_catalog.values() if a.owner_id == OWNER]
    parent = _pick(actions, "blossom.cultivate").source_definition_id
    entry = next(row for row in state["shapes"][OWNER] if row["base"] == parent)
    labels = [row["label"] for row in entry["choices"]]
    assert labels == sorted(labels)
    assert any("Medicinal" in label for label in labels) and any("Thorned" in label for label in labels)
    assert all(row["button_id"].startswith("act:") and row["candidate_id"] for row in entry["choices"])
    for picker in state["menu"]["actions"]:
        if picker["source_definition_id"].endswith(("blossom.pick.medicinal", "blossom.pick.thorned")):
            assert picker["shape"] == parent
