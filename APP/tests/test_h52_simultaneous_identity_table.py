"""CL20 second-choice persistence through real TabletopService actions."""
from __future__ import annotations

import json

import pytest

from h52_identity_support import choose, committed_state, fight, roster


@pytest.mark.parametrize(("owner_name", "choices", "condition_id", "second_feature", "recorded_forms"), [
    # The Golden Core Form(s) are recorded on the sheet (a fixed build choice), so the
    # CL20 pair is a build record that survives reload rather than two in-fight switches.
    ("Lingyue Frostveil", [], "condition:typed.golden_core_form",
     "second_golden_core_form", ("reservoir", "circulating")),
    ("Ning Kai", ["Core Tempering Expression: Blood-Furnace Circulation",
                   "Core Tempering Expression: Mountain-Rending Pulse"],
     "condition:typed.core_tempering_expression", "second_core_tempering_expression", ()),
])
def test_real_cl20_character_keeps_two_selections_through_table_reload(
        tmp_path, owner_name, choices, condition_id, second_feature, recorded_forms):
    fighters = roster()
    owner = next(row for row in fighters if row["name"] == owner_name)
    friends = [row for row in fighters if row is not owner and row["cl"] <= 10]
    assert owner["cl"] == 20
    assert any(value.endswith(second_feature) for value in owner["features"])
    if recorded_forms:
        owner = {**owner, "sheet": json.loads(json.dumps(owner["sheet"]))}
        owner["sheet"].setdefault("path_and_subpath", {})["golden_core_forms"] = list(recorded_forms)
    characters = [owner, friends[0], friends[1], friends[2]]
    _user, service, table, mid, owner_entity = fight(
        tmp_path, characters, "H52-L43-" + owner_name.replace(" ", "-"))
    for choice_text in choices:
        choose(service, table, mid, owner_entity, choice_text)
    final = committed_state(service, mid)
    held = [row for row in final["actors"][owner_entity]["conditions"].values()
            if row["condition_id"] == condition_id]
    assert len(held) == 2
    assert owner_entity in final["actors"]


# ------------------------------------------------------------------------------------------- in-repo characters
# Printed: "At CL20, choose a second Golden Core Form. Both Forms are Perfected." / "At CL20, choose a second expression.
# Both expressions function simultaneously, and both use their Perfected benefits."
from h52_identity_support import (BODY_TWO_EXPRESSIONS, CLOSE_STARTS, QI_TWO_FORMS, character, commit,  # noqa: E402
                                  labels, option, turn_of)

PB, KEY_MOD = 4, 2  # compiled_sheet: proficiency +4, every ability 14
FILLERS = [character("52b00011", "Sparring Partner", [], cl=10), character("52b00012", "Second Foe", [], cl=10),
           character("52b00013", "Third Foe", [], cl=10)]


def _events_since(service, mid, start, event_type, source_part):
    return [e for e in service._load_session(mid).engine.events[start:]
            if e.event_type == event_type and source_part in e.source_definition_id]


def test_cl20_two_golden_core_forms_both_apply_their_perfected_benefits(tmp_path):
    owner = character("52b00001", "Two-Form Qi", QI_TWO_FORMS, cl=20)
    owner["sheet"]["path_and_subpath"]["golden_core_forms"] = ["circulating", "reservoir"]  # both Forms fixed on the sheet
    _user, service, table, mid, owner_id = fight(tmp_path, [owner, *FILLERS], "H52-TWO-FORMS", starts=CLOSE_STARTS)
    foe_id = "actor:factory." + FILLERS[1]["pid"]
    state = turn_of(table, mid, owner_id)
    assert not {label for label in labels(state) if label.startswith("Golden Core Form:")}  # fixed, not offered
    start = len(service._load_session(mid).engine.events)
    commit(table, mid, option(table.state(mid), "Tears Like Pearls", foe_id))  # a Qi technique: Circulating
    commit(table, mid, option(table.state(mid), "Golden Core Reservoir"))  # Reservoir's Bonus Action
    final = committed_state(service, mid)
    me = final["actors"][owner_id]
    forms = sorted((row["data"] or {}).get("form") for row in me["conditions"].values()
                   if row["condition_id"] == "condition:typed.golden_core_form")
    assert forms == ["circulating", "reservoir"]
    circulating = _events_since(service, mid, start, "TEMP_HP_GRANTED", "golden_core_form.circulating")
    assert [e.payload["offered"] for e in circulating] == [2 * PB]  # Perfected Circulating: 2 x PB temporary HP
    assert me["temporary_hp"] == 2 * PB
    reservoir = [e for e in _events_since(service, mid, start, "RESOURCE_GAINED", "qi_path.reservoir")
                 if e.payload["resource_id"] == "resource:core.qi"]
    assert [e.payload["requested"] for e in reservoir] == [2 * PB + KEY_MOD]  # Perfected Reservoir: 2 x PB + key
    assert me["resources"]["resource:core.qi"] == 30  # 30 - 1 for Tears, then refilled to the maximum


def test_cl20_two_core_tempering_expressions_both_apply_their_perfected_benefits(tmp_path):
    owner = character("52b00002", "Two-Expression Body", BODY_TWO_EXPRESSIONS, cl=20, primary="Stamina")
    _user, service, table, mid, owner_id = fight(tmp_path, [owner, *FILLERS], "H52-TWO-EXPRESSIONS", starts=CLOSE_STARTS)
    foe_id = "actor:factory." + FILLERS[1]["pid"]
    state = turn_of(table, mid, owner_id)
    commit(table, mid, option(state, "Core Tempering Expression: Blood-Furnace Circulation"))
    commit(table, mid, option(table.state(mid), "Core Tempering Expression: Mountain-Rending Pulse"))
    assert not {label for label in labels(table.state(mid)) if label.startswith("Core Tempering Expression:")}
    start = len(service._load_session(mid).engine.events)
    commit(table, mid, option(table.state(mid), "Iron Voice", foe_id))  # one Stamina spent on a feature
    final = committed_state(service, mid)
    me = final["actors"][owner_id]
    expressions = sorted((row["data"] or {}).get("expression") for row in me["conditions"].values()
                         if row["condition_id"] == "condition:typed.core_tempering_expression")
    assert expressions == ["blood_furnace", "mountain_rending"]
    furnace = _events_since(service, mid, start, "TEMP_HP_GRANTED", "core_tempering_expression")
    assert [e.payload["offered"] for e in furnace] == [2 * PB]  # Perfected Blood-Furnace at full HP: 2 x PB temp HP
    assert me["temporary_hp"] == 2 * PB
    assert [row["condition_id"] for row in me["conditions"].values()].count("condition:typed.mountain_rending_ready") == 1
    button = next(row for row in table.sheet(owner["pid"])["buttons"]
                  if row.get("label") == "Core Tempering Expression: Mountain-Rending Pulse")
    assert "choose two different Expressions; both work at the same time" in json.dumps(button)




def test_one_slot_characters_keep_their_earlier_choice_rules(tmp_path):
    """Without the CL20 second-choice feature the plug-ins behave as before: a CL17 Qi owner holds the one Form
    recorded on the sheet and offers no in-fight choice; a CL17 Body owner's one Expression is fixed once picked; others get neither choice."""
    qi = character("52b00003", "One-Form Qi", QI_TWO_FORMS[:2] + QI_TWO_FORMS[3:], cl=17)
    qi["sheet"]["path_and_subpath"]["golden_core_forms"] = ["circulating"]  # the one Form, fixed on the sheet
    body = character("52b00004", "One-Expression Body", BODY_TWO_EXPRESSIONS[:2] + BODY_TWO_EXPRESSIONS[3:], cl=17,
                     primary="Stamina")
    _user, service, table, mid, qi_id = fight(tmp_path, [qi, body, *FILLERS[:2]], "H52-ONE-SLOT",
                                              (qi["pid"], body["pid"], FILLERS[0]["pid"]), starts=CLOSE_STARTS)
    body_id, plain_id = "actor:factory." + body["pid"], "actor:factory." + FILLERS[0]["pid"]
    assert not {label for label in labels(turn_of(table, mid, qi_id)) if label.startswith("Golden Core Form:")}
    commit(table, mid, table.state(mid)["menu"]["end_turn"])
    commit(table, mid, option(turn_of(table, mid, body_id), "Core Tempering Expression: Blood-Furnace Circulation"))
    assert not {label for label in labels(table.state(mid)) if label.startswith("Core Tempering Expression:")}
    commit(table, mid, table.state(mid)["menu"]["end_turn"])
    plain = labels(turn_of(table, mid, plain_id))
    assert not {label for label in plain if label.startswith(("Golden Core", "Core Tempering", "Sovereign"))}
    final = committed_state(service, mid)
    held = {actor_id: sorted((row["data"] or {}).get(key) for row in final["actors"][actor_id]["conditions"].values()
                             if row["condition_id"] == condition_id)
            for actor_id, condition_id, key in ((qi_id, "condition:typed.golden_core_form", "form"),
                                                (body_id, "condition:typed.core_tempering_expression", "expression"))}
    assert held == {qi_id: ["circulating"], body_id: ["blood_furnace"]}
    assert "two different Expressions" not in json.dumps(table.sheet(body["pid"])["buttons"])
