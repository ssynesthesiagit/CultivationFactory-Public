"""Compilation regressions for the real printed Yang lighting reactions."""
from combat.factory_compiler import compile_character
from combat.reaction_triggers import classify_mechanic_all
from tests.h1_support import mechanics, sheet

SMALL = "TAL_YANG_THE_ACTION_CANNOT_STAY_SMALL"


def test_action_cannot_stay_small_has_a_runnable_trigger_and_compiles():
    record = mechanics()[SMALL]
    matches = classify_mechanic_all(record)
    assert any(match.runnable for match in matches), (record["activation"], matches)
    bundle = compile_character(sheet([SMALL]), actor_id="actor:test.yang")
    assert any(row.get("feature_id") == SMALL for row in bundle["typed_reactions"]), {
        "record": record, "matches": matches, "diagnostics": bundle.get("diagnostics"),
        "reaction_ids": [row.get("feature_id") for row in bundle["typed_reactions"]],
    }
