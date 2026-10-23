"""Silence transmission uses the public zone geometry contract after reload."""
from combat import zones
from combat.ext.smoke_sound_residual import silence_field_path
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, settle


def test_silence_path_uses_public_containment_for_both_endpoints(tmp_path, monkeypatch):
    _, table, mid = fixture(
        tmp_path, ["TAL_SOUND_FORBIDDEN_SILENCE_FIELD"],
        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 0, "y": 6},
                   FOE: {"x": 11, "y": 6}}, seed="F15-PUBLIC-CONTAINMENT")
    engine = reload(tmp_path, mid)
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name.split(" at ")[0] == "Forbidden Silence Field"
                     and c.destination is not None
                     and (c.destination.x, c.destination.y) == (5, 6))
    settle(table, mid, candidate.candidate_id)
    engine = reload(tmp_path, mid)
    calls = []
    contains = zones.actor_inside_zone

    def public_contains(live, actor, zone, position=None):
        result = contains(live, actor, zone, position)
        calls.append((actor.entity_id, result))
        return result

    monkeypatch.setattr(zones, "actor_inside_zone", public_contains)
    actors = engine.state.actors
    assert silence_field_path(engine, actors[OWNER], actors[FOE], "test:sound") is False
    assert calls == [(OWNER, True), (FOE, False)]
    calls.clear()
    assert silence_field_path(engine, actors[FOE], actors[OWNER], "test:sound") is False
    assert calls == [(FOE, False), (OWNER, True)]
    calls.clear()
    assert silence_field_path(engine, actors[ALLY], actors[FOE], "test:sound") is False
    assert calls == [(ALLY, False), (FOE, False)]
