"""Regressions for the F18R Cultivated Response review findings (F19 fix round).

Each test fails on the F18R record and passes once its fix is in place.
"""
import json
import re

from tests.h1_support import ROOT

AUTO3 = ROOT / "authority/typed_mechanics/reviewed_final.d/auto3_foundations.json"
GENERATED = ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json"
RULES_TEXT = ROOT / "authority/typed_mechanics/rules_text.json"
CULTIVATED = "tianxia.path.qi_cultivation.feature.cultivated_response"
NASCENT = "tianxia.path.qi_cultivation.feature.nascent_soul"
PENDING = "OWNER-PENDING TABLE RULING"
UNSOURCED = re.compile(r"first-turn|before your first Action|costs no action|costs no action or resource|TABLE NOTE", re.I)


def _riders(feature):
    return json.loads(AUTO3.read_text(encoding="utf-8"))["mechanics"][feature]["riders"]


def _printed_cannot_modify_clauses():
    text = json.loads(RULES_TEXT.read_text(encoding="utf-8"))[CULTIVATED]
    return [line[2:].rstrip(".") for line in text.splitlines() if line.startswith("- Cannot modify ")]


# F18R finding 1: every printed "Cannot modify" clause is a rider on the reviewed record and on the generated authority.
def test_f18r1_every_printed_cannot_modify_clause_is_a_rider():
    clauses = _printed_cannot_modify_clauses()
    assert len(clauses) == 4, clauses
    riders = [r.rstrip(".").lower() for r in _riders(CULTIVATED)]
    generated = json.loads(GENERATED.read_text(encoding="utf-8"))["mechanics"][CULTIVATED]["riders"]
    generated = [r.rstrip(".").lower() for r in generated]
    for clause in clauses:
        expected = ("cultivated response " + clause).lower()
        assert expected in riders, clause
        assert expected in generated, clause


def test_f18r1_death_save_and_same_save_clauses_are_named():
    riders = " ".join(_riders(CULTIVATED))
    assert "Cultivated Response cannot modify a death saving throw." in riders
    assert "Cultivated Response cannot modify the same saving throw more than once." in riders


# F18R finding 2: unsourced timing or cost rulings are not stated as printed rules; they carry the owner-pending label.
def test_f18r2_no_unlabelled_table_ruling_on_cultivated_response():
    for rider in _riders(CULTIVATED):
        if UNSOURCED.search(rider):
            assert rider.startswith(PENDING), rider


def test_f18r2_pending_ruling_is_present_and_marks_itself_unapproved():
    pending = [r for r in _riders(CULTIVATED) if r.startswith(PENDING)]
    assert len(pending) == 1
    assert "not printed" in pending[0] and "not yet approved" in pending[0]


# F18R finding 3: the rewritten riders do not carry the old auto3 attestation.
def test_f18r3_changed_riders_are_not_attested_under_the_old_entry():
    for feature in (CULTIVATED, NASCENT):
        data = json.loads(AUTO3.read_text(encoding="utf-8"))["mechanics"][feature]
        assert data["reviewed_by"] != "auto3 2026-10-04", feature
        assert data["reviewed_by"].startswith("PENDING auto3 re-review"), feature


# F18R finding 3 (generated side): the generated authority matches the reviewed riders for the two records.
def test_f18r3_generated_authority_matches_reviewed_riders_for_both_features():
    generated = json.loads(GENERATED.read_text(encoding="utf-8"))["mechanics"]
    for feature in (CULTIVATED, NASCENT):
        assert generated[feature]["riders"] == _riders(feature), feature
