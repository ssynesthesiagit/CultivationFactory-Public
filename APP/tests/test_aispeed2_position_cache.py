"""Position-projected flight answers must not leak between route squares."""
from types import SimpleNamespace

from combat import flight, read_queries
from combat.gate2_runtime_models import Position


def test_flight_profile_cache_distinguishes_projected_positions(monkeypatch):
    actor = SimpleNamespace(position=Position(x=0, y=0), conditions={})
    engine = SimpleNamespace(state=SimpleNamespace(state_version=0, event_sequence=0))
    monkeypatch.setattr(flight, "_capability", lambda engine, actor, excluded:
                        (10 if actor.position.x == 0 else 30, False, False, False, False))
    with read_queries.read_frame(engine):
        first = flight.profile(engine, actor)
        actor.position = Position(x=1, y=0)
        second = flight.profile(engine, actor)
    assert first.speed_ft == 10
    assert second.speed_ft == 30
