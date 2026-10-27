"""A configured rider cannot force a save without paying for that hit."""
from tests.test_mgr_t17_shield_hacking_rhythm import (
    _fight, _configure_shield_hacking, _hit_with, EDGE, CONDITION,
)


def test_configured_hit_without_edge_never_saves():
    engine, me, foe = _fight(shield=True, edge=0)
    _configure_shield_hacking(engine)
    before = sum(e.event_type == "SAVE_ROLLED" for e in engine.events)
    _hit_with(engine, "Forward Cut")
    assert me.resources[EDGE] == 0
    assert sum(e.event_type == "SAVE_ROLLED" for e in engine.events) == before
    assert not any(c.condition_id == CONDITION for c in foe.conditions.values())
