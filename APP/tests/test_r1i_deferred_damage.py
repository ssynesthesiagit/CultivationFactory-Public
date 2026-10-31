"""Automated deferred damage must also resolve its damage-ending effects.

riders/c17 (ad29d87d, approved C17r5.review.md; merged ae0ddddc) replaces
the old GM fallback with nested-aware native damage and Beast Tamer cleanup.
"""
from combat import typed_executor as te
from combat.ext.beastmastery_riders import PREFIX
from tests.test_riders_lane1 import _rider_engine, _rider_use, _answers, BLACK_SUN, ME, AN


def test_black_sun_spend_is_explicitly_gm_run_and_cannot_leave_automated_damage_with_stale_control():
    """Keep this historical node ID; C17 now requires automation, not a GM notice."""
    engine = _rider_engine(BLACK_SUN)
    subject = engine.state.actors[AN]
    engine._apply_condition(subject, "condition:typed.charmed", "test:tamer", ME, expires_on="UNTIL_REMOVED")
    owned = next(c.instance_id for c in subject.conditions.values() if c.source_definition_id == "test:tamer")
    engine._apply_condition(subject, PREFIX + "beast_tamer", "test:tamer", ME, expires_on="UNTIL_REMOVED",
                            data={"conditions": [owned], "modifiers": []})
    _answers(engine, {"black_sun_damage": ["necrotic"]})
    _rider_use(engine, BLACK_SUN)
    subject.resources["resource:core.qi"] = subject.resource_maximums["resource:core.qi"] = 10
    hp, start = subject.current_hp, len(engine.events)
    engine._spend_resource(subject, "resource:core.qi", 1, "test:spend")
    events = engine.events[start:]
    damage = [e for e in events if e.event_type == "DAMAGE_COMMITTED"]
    assert len(damage) == 1
    assert damage[0].payload["damage_type"] == "NECROTIC"
    assert subject.current_hp == hp - damage[0].payload["hp_damage"] < hp
    assert not any(e.event_type == "GM_RIDER" for e in events)
    assert owned not in subject.conditions
    assert not any(c.condition_id == PREFIX + "beast_tamer" for c in subject.conditions.values())
    start = len(engine.events)
    engine._spend_resource(subject, "resource:core.qi", 1, "test:again")
    assert not any(e.event_type == "DAMAGE_COMMITTED" for e in engine.events[start:])
    assert not any(e.event_type == "GM_RIDER" for e in engine.events[start:])
