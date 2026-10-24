"""Regressions for the F19R Cultivated Response review findings (F20 fix round).

Each test fails on the F19R record and passes once its fix is in place.
"""
import json

from tests.h1_support import ROOT

AUTO3 = ROOT / "authority/typed_mechanics/reviewed_final.d/auto3_foundations.json"
CULTIVATED = "tianxia.path.qi_cultivation.feature.cultivated_response"
NASCENT = "tianxia.path.qi_cultivation.feature.nascent_soul"
UNAPPROVED = ("first-turn", "costs no action", "lasts for this fight", "permanent", "cannot replace a previous")


def _riders(feature):
    return json.loads(AUTO3.read_text(encoding="utf-8"))["mechanics"][feature]["riders"]


# F19R finding 1: the player-facing Discipline button text does not state the OWNER-PENDING timing or cost as fact.
def test_f19r1_discipline_button_text_states_no_unapproved_ruling():
    from combat.ext import defensive_disciplines as dd

    for ability in ("DEX", "INT", "CHA"):
        text = dd._description(CULTIVATED, ability)
        for phrase in UNAPPROVED:
            assert phrase not in text, (ability, phrase, text)
        assert "Proficiency Bonus" in text and "once per round" in text


def test_f19r1_discipline_prompt_cost_states_no_unapproved_ruling():
    source = (ROOT / "combat/ext/defensive_disciplines.py").read_text(encoding="utf-8")
    assert "Choosing costs no action or resource" not in source
    assert "Your choice lasts for this fight" not in source
    assert "during your first-turn setup" not in source


# F19R finding 2: the table-facing "which saving throw" question is a rider again on Cultivated Response.
def test_f19r2_cultivated_response_rider_asks_the_table_which_saving_throw():
    riders = _riders(CULTIVATED)
    assert any("table decides which saving throw" in r and "person running the game" in r for r in riders), riders


def test_f19r2_nascent_soul_rider_keeps_the_table_agreement():
    assert any("Agree their saving throws with the person running the game" in r for r in _riders(NASCENT))
