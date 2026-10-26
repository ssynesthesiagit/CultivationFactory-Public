"""Mutation regressions for the three PRIVCONV review findings; no private fixtures."""
import copy
import json
from pathlib import Path

import pytest

from tests import test_auto1_paths_a as paths
from tests import test_auto82_needle_riders as needle
from tests import test_mgr14_saber_method as saber


def _replace_json(monkeypatch, filename, mutate):
    original = Path.read_text

    def read(path, *args, **kwargs):
        text = original(path, *args, **kwargs)
        if path.name == filename:
            document = json.loads(text)
            mutate(document)
            return json.dumps(document)
        return text

    monkeypatch.setattr(Path, "read_text", read)


def test_wrong_printed_clause_is_not_accepted(monkeypatch):
    from combat import rule_help
    monkeypatch.setattr(rule_help, "printed_rule_text", lambda _: "Unrelated printed clause.")
    with pytest.raises(AssertionError, match="clause content changed"):
        paths.test_the_printed_procedure_lines_a_path_feature_enforces_are_marked_as_covered(paths.TEMPERED)


def test_covers_cannot_be_associated_with_another_feature(monkeypatch):
    from combat import typed_reactions
    blocks = copy.deepcopy(typed_reactions.rules())
    features = blocks["features"]
    features[paths.TEMPERED]["covers"] = features[paths.EXTRA_ATTACK]["covers"]
    monkeypatch.setattr(typed_reactions, "rules", lambda: blocks)
    with pytest.raises(AssertionError, match="clause content changed"):
        paths.test_the_printed_procedure_lines_a_path_feature_enforces_are_marked_as_covered(paths.TEMPERED)


@pytest.mark.parametrize("record,check", [
    (paths.THOUSAND, paths.test_thousand_hand_incarnation_no_longer_says_its_extra_reaction_is_the_gms),
    ("TAL_FENCING_VACUUM_CUT",
     needle.test_vacuum_cut_still_asks_the_game_master_about_a_turn_on_which_no_weapon_was_drawn),
    ("TAL_FENCING_SOVEREIGN_NEEDLE_INCARNATION",
     needle.test_the_four_records_with_nothing_left_to_ask_carry_no_rider),
])
def test_same_rider_count_with_unrelated_content_is_rejected(monkeypatch, record, check):
    def mutate(document):
        document["mechanics"][record]["riders"] = ["An unrelated reminder."]
    _replace_json(monkeypatch, "Tianxia_Typed_Mechanics_Authority_R1.json", mutate)
    with pytest.raises(AssertionError, match="clause content changed"):
        check()


@pytest.mark.parametrize("filename", ["rules_text.json", "player_text.json",
                                      "Tianxia_Typed_Mechanics_Authority_R1.json"])
def test_saber_clauses_cannot_disappear_behind_valid_metadata(monkeypatch, filename):
    def mutate(document):
        if filename == "rules_text.json":
            document[saber.MECH] = "Range: Self\nCost: None\nUnrelated printed clause."
        elif filename == "player_text.json":
            document["records"][saber.MECH] = "Range: Self\nCost: None\nUnrelated player text."
        else:
            document["mechanics"][saber.MECH]["riders"] = ["Unrelated reminder."] * 3
    _replace_json(monkeypatch, filename, mutate)
    with pytest.raises(AssertionError, match="clause content changed"):
        saber.test_the_full_printed_row_stays_typed_and_reaches_the_player_text()
