"""Public Shield fixtures restore semantic inputs, not production functions."""
import copy

from combat.factory_compiler import compile_character
from tests.active_defense_authority_support import DEFENSE, TRIGGER, fixture_authority, install
from tests.h1_support import sheet


def test_fixture_repairs_replaced_prose_without_mutating_other_records():
    public = {"mechanics": {
        DEFENSE: {"activation": {"trigger": "[public prose replacement]"}, "effects": []},
        "other": {"activation": {"trigger": "unchanged"}, "effects": []}}}
    before = copy.deepcopy(public)
    restored = fixture_authority(public)
    assert public == before
    assert restored["mechanics"]["other"] == before["mechanics"]["other"]
    record = restored["mechanics"][DEFENSE]
    assert record["activation"]["trigger"] == TRIGGER
    assert record["effects"][0]["flat"] == 2


def test_synthetic_source_compiles_owned_defense_and_leaves_nonowners_inert(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    bundle = compile_character(sheet([DEFENSE]), actor_id="actor:test.shield_reading",
                               reaction_plan={"ask": True})
    rows = [r for r in bundle["typed_reactions"] if r.get("feature_id") == DEFENSE]
    assert len(rows) == 1 and rows[0]["kind"] == "attacked"
    assert rows[0]["ask"] and rows[0]["after_attack_roll"]
    assert rows[0]["effects"][0]["flat"] == 2
    assert rows[0]["effects"][0]["duration"] == "triggering_attack"
    plain = compile_character(sheet([]), actor_id="actor:test.no_shield")
    assert not any(r.get("feature_id") == DEFENSE for r in plain["typed_reactions"])
