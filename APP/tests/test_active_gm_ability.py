"""A lasting ability whose effects the GM applies leaves a marker on its user for its duration (owner 2026-09-29: Court of
Measured Openings was cast and nothing showed it was up)."""

from combat import typed_executor
from tests.test_effect_durations import _ctx, _end_turn, _fight


def _cast(engine, me, duration, effects=(), riders=("Court of Measured Openings (1 minute): one Feint each turn with no Action.",)):
    ctx = _ctx(engine, me, me, duration)
    ctx.typed["riders"] = list(riders)
    ctx.typed["effects"] = list(effects)
    first = len(engine.events)
    typed_executor._mark_lasting_gm_ability(ctx, first, list(riders))
    return [c for c in me.conditions.values() if c.condition_id == typed_executor.ACTIVE_ABILITY]


def test_a_one_minute_gm_ability_shows_on_its_user_and_ends_on_time():
    engine, me, foe = _fight("ACTIVE")
    marks = _cast(engine, me, {"kind": "minutes", "amount": 1, "concentration": False})
    assert len(marks) == 1 and "(1 minute)" in marks[0].data["label"] and "Feint" in marks[0].data["reading"]
    assert marks[0].expires_on and marks[0].expires_on != "UNTIL_REMOVED"


def test_nothing_for_an_instant_one_or_one_the_fight_runs():
    engine, me, foe = _fight("ACTIVE")
    assert not _cast(engine, me, {"kind": "instant"})
    assert not _cast(engine, me, {"kind": "minutes", "amount": 1}, effects=[{"type": "temp_hp", "applies_to": "self", "flat": 2}])
