"""Active Defense's source-bound trigger must not depend on prose heuristics."""
import json
from pathlib import Path

from combat import reaction_triggers
from combat.factory_compiler import compile_character
from tests.h1_support import sheet

ROOT = Path(__file__).resolve().parents[1]
DEFENSE = "SHIELD_BASE_ACTIVE_DEFENSE"


def test_active_defense_has_an_exact_printed_trigger_reading():
    mechanic = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json")
                          .read_text())["mechanics"][DEFENSE]
    readings = reaction_triggers.readings_for(mechanic)
    assert readings is not None and [r.kind for r in readings] == ["attacked"]
    # An owner text edit must invalidate this reading, not silently retain it.
    edited = {**mechanic, "activation": {**mechanic["activation"],
                                       "trigger": "A different printed trigger"}}
    assert reaction_triggers.readings_for(edited) is None


def test_owned_defense_compiles_even_when_the_phrase_classifier_cannot_read_it(monkeypatch):
    monkeypatch.setattr(reaction_triggers, "classify_trigger",
                        lambda *_: reaction_triggers.TriggerMatch(kind="unsupported"))
    bundle = compile_character(sheet([DEFENSE]), actor_id="actor:test.shield_reading",
                               reaction_plan={"ask": True})
    rows = [r for r in bundle["typed_reactions"] if r.get("feature_id") == DEFENSE]
    assert len(rows) == 1 and rows[0]["kind"] == "attacked"
    assert rows[0]["ask"] and rows[0]["after_attack_roll"]
    assert rows[0]["effects"][0]["flat"] == 2
    assert rows[0]["effects"][0]["duration"] == "triggering_attack"
    assert not rows[0].get("requires_sight")  # awareness is not sight-only
    plain = compile_character(sheet([]), actor_id="actor:test.no_shield")
    assert not any(r.get("feature_id") == DEFENSE for r in plain["typed_reactions"])
