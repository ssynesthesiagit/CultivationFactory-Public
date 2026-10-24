"""Defensive Discipline is a build choice recorded on the character sheet (set at creation or level-up).

The pick is never asked in a fight. The compiler reads the recorded picks into the save_rescue row, the same
way for a player and an AI fighter. A character with nothing recorded (built before the choice existed) keeps
the compiled weakest-save row and shows as unchosen.
"""
import json
from pathlib import Path

import pytest

from combat.typed_reactions import compile_blocks

ROOT = Path(__file__).resolve().parents[1]
TEMPERED = "tianxia.path.body_refining.feature.tempered_response"
CULTIVATED = "tianxia.path.qi_cultivation.feature.cultivated_response"
NASCENT = "tianxia.path.qi_cultivation.feature.nascent_soul"
IMMORTAL = "tianxia.path.qi_cultivation.feature.immortal_of_qi"
BUILD = json.loads((ROOT / "rules/feature_build_choices.json").read_text())
SAVES = {"STR": 2, "DEX": 3, "CON": 1, "INT": 0, "CHA": 0}
RESOURCES = {"qi": "qi", "stamina": "stamina"}


def _rows(build_choices, *ids):
    result = compile_blocks(list(ids), pb=2, key_mod=0, saves=SAVES, resource_ids=RESOURCES, cl=20,
                            mechanics={}, build_choices=build_choices)
    return {row["feature_id"]: row for row in result["reactions"] if row.get("block") == "save_rescue"}


def _pick(source, code):
    return {source: {"defensive_discipline": code}}


def test_tempered_response_uses_the_recorded_pick():
    row = _rows(_pick(TEMPERED, "DEX"), TEMPERED)[TEMPERED]
    assert row["abilities"] == ["DEX"]
    assert row["chosen"] is True


def test_unchosen_tempered_response_keeps_the_weakest_listed_save_and_says_so():
    row = _rows({}, TEMPERED)[TEMPERED]
    assert row["abilities"] == [min(["STR", "DEX", "CON"], key=lambda a: (SAVES[a], a))]
    assert row["chosen"] is False
    assert sorted(row["choices"]) == ["CON", "DEX", "STR"]


def test_a_pick_outside_the_printed_options_is_ignored():
    row = _rows(_pick(TEMPERED, "INT"), TEMPERED)[TEMPERED]
    assert row["chosen"] is False
    assert row["abilities"] == [min(["STR", "DEX", "CON"], key=lambda a: (SAVES[a], a))]


def test_cultivated_response_collects_its_later_disciplines_at_compile():
    picks = {CULTIVATED: {"defensive_discipline": "DEX"},
             NASCENT: {"defensive_discipline": "INT"},
             IMMORTAL: {"defensive_discipline": "CHA"}}
    row = _rows(picks, CULTIVATED, NASCENT, IMMORTAL)[CULTIVATED]
    assert sorted(row["abilities"]) == ["CHA", "DEX", "INT"]


def test_cultivated_response_with_only_the_first_pick_covers_one_save():
    row = _rows(_pick(CULTIVATED, "CHA"), CULTIVATED)[CULTIVATED]
    assert row["abilities"] == ["CHA"]


def test_each_defensive_discipline_option_is_labelled_for_a_newcomer():
    data = BUILD[TEMPERED]
    assert data["prompt"]
    labels = {option["id"]: option["name"] for option in data["options"]}
    assert labels == {"str": "Strength (Rooted Frame)", "dex": "Dexterity (Flowing Frame)",
                      "con": "Constitution (Enduring Frame)"}
    for option in data["options"]:
        assert option["grants"] == {"defensive_discipline": option["id"].upper()}


def test_cultivated_response_options_match_the_printed_disciplines():
    for source in (CULTIVATED, NASCENT, IMMORTAL):
        names = [option["name"] for option in BUILD[source]["options"]]
        assert names == ["Dexterity (Reflexive Circulation)", "Intelligence (Calculated Circulation)",
                         "Charisma (Imperious Circulation)"], (source, names)


def test_the_stored_pick_is_a_string_only():
    for source, data in BUILD.items():
        if "defensive_discipline" not in json.dumps(data):
            continue
        for option in data["options"]:
            assert all(isinstance(value, str) for value in option["grants"].values()), (source, option)


def test_the_in_fight_pick_plug_in_is_gone():
    with pytest.raises(ImportError):
        import combat.ext.defensive_disciplines  # noqa: F401
