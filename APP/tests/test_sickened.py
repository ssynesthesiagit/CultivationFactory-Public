"""Sickened (Disease; fight audit 2026-09-29: "Condition not in the rules file: sickened"): Disadvantage on Constitution
checks and Concentration saves, and healing halved."""

from combat import concentration, typed_executor
from tests.test_reaction_reach import _ctx, _engine, ME


def test_sickened_presses_concentration_con_checks_and_halves_healing():
    engine = _engine({"x": 1, "y": 1}, {"x": 2, "y": 1})
    me = engine.state.actors[ME]
    typed_executor.run_effects(_ctx(engine, me, me), [{"type": "condition", "condition": "sickened", "applies_to": "self", "expires_on": "UNTIL_REMOVED"}])
    assert not any(e.event_type == "GM_RIDER" and "not in the rules file" in str(e.payload) for e in engine.events)
    assert concentration.save_mode(engine, me) == "DISADVANTAGE"
    assert typed_executor.check_mode(me, "CON") == "DISADVANTAGE" and typed_executor.check_mode(me, "STR") == "NORMAL"
    assert typed_executor._reduced_healing(engine, me, 10) == 5
