"""Position-projected flight and sight answers must not leak between route squares."""
from types import SimpleNamespace

from combat import flight, read_queries
from combat.gate2_runtime_models import Position
from tests.test_ai_flight_options import FLYER, GROUND, flyer_fight


def test_flight_profile_cache_distinguishes_projected_positions(monkeypatch):
    actor = SimpleNamespace(position=Position(x=0, y=0), conditions={})
    engine = SimpleNamespace(state=SimpleNamespace(state_version=0, event_sequence=0),
                             _effective_speed=lambda actor: 30)
    monkeypatch.setattr(flight, "_capability", lambda engine, actor, excluded:
                        (10 if actor.position.x == 0 else 30, False, False, False, False))
    with read_queries.read_frame(engine):
        first = flight.profile(engine, actor)
        actor.position = Position(x=1, y=0)
        second = flight.profile(engine, actor)
    assert first.speed_ft == 10
    assert second.speed_ft == 30


def test_can_see_reuses_no_sight_answer_across_projected_squares(tmp_path):
    """One mover object at two squares must keep the sight answer of each square."""
    from combat.target_knowledge import can_see

    combat, _, mid, _ = flyer_fight(tmp_path)
    engine = combat._load_session(mid).engine
    target = engine.state.actors[GROUND]
    mover = engine.state.actors[FLYER].model_copy()
    # The arena wall stands on x=5; the target is at x=4.
    far = target.position.model_copy(update={"x": 7, "y": 4})
    with read_queries.read_frame(engine):
        assert can_see(engine, mover, target) is True
        mover.position = far
        assert can_see(engine, mover, target) is False
