"""Compilation regressions for the real printed Yang lighting reactions."""
import copy
import hashlib

from combat.factory_compiler import compile_character
from factory_authoring.trigger_mechanics import seal_trigger_events
from combat.reaction_triggers import classify_mechanic_all
from tests.h1_support import mechanics, sheet

SMALL = "TAL_YANG_THE_ACTION_CANNOT_STAY_SMALL"


def test_reviewed_events_survive_changed_display_prose_without_losing_limits():
    trigger = "A marked creature completes an action"
    event = {"kind": "creature_acted", "range_ft": 90, "requires_mark": "*"}
    record = {"mechanic_id": "test:completion", "activation": {"trigger": trigger}}
    reading = {("test:completion", hashlib.sha256(trigger.encode()).hexdigest()): {"events": [event]}}
    seal_trigger_events({"test:completion": record}, reading)
    record["activation"]["trigger"] = "unrecognizable presentation text"
    match, = classify_mechanic_all(record)
    assert (match.kind, match.range_ft, match.requires_mark, match.runnable) == ("creature_acted", 90, "*", True)
    assert reading[next(iter(reading))]["events"] == [event]


def test_source_edits_invalidate_reviewed_events_at_build_time():
    trigger = "The marked subject moves at least 10 feet"
    record = {"mechanic_id": "test:movement", "activation": {"trigger": trigger}}
    event = {"kind": "moved", "requires_mark": "Overkindled Mark", "min_move_ft": 10}
    readings = {("test:movement", hashlib.sha256(trigger.encode()).hexdigest()): {"events": [event]}}
    seal_trigger_events({"test:movement": record}, readings)
    sealed = copy.deepcopy(record["activation"]["trigger_events"])
    assert sealed == [event]
    record["activation"]["trigger"] = "A different rule"
    seal_trigger_events({"test:movement": record}, readings)
    assert "trigger_events" not in record["activation"]


def test_action_cannot_stay_small_has_a_runnable_trigger_and_compiles():
    record = mechanics()[SMALL]
    matches = classify_mechanic_all(record)
    assert any(match.runnable for match in matches), (record["activation"], matches)
    bundle = compile_character(sheet([SMALL]), actor_id="actor:test.yang")
    assert any(row.get("feature_id") == SMALL for row in bundle["typed_reactions"]), {
        "record": record, "matches": matches, "diagnostics": bundle.get("diagnostics"),
        "reaction_ids": [row.get("feature_id") for row in bundle["typed_reactions"]],
    }
