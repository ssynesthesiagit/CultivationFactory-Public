"""One walking search per reachable() call: a flying creature's walking routes have one source and one merge.

Before this change flight.reachable() gathered walking from two places (the grid search on the
ground and the volume search when spatially scoped) and merged them after the fact. These tests
pin the single owner (flight._walking_routes) and default-inert behaviour for a walker on the ground.
"""
from combat import flight
from tests.test_mgr_t14_riverway_travel_fixes import fight
from tests.test_shared_movement_seams import _flying_engine
from tests.worker2_support import OWNER


def test_flying_creature_walking_alternatives_come_from_exactly_one_search(monkeypatch):
    """A flying creature with no scoped walking source still asks the one walking owner exactly once."""
    engine = _flying_engine()
    actor = engine.state.actors[engine.state.current_actor_id]
    calls = []
    original = flight._walking_routes

    def record(*args, **kwargs):
        calls.append(kwargs.get("flying"))
        return original(*args, **kwargs)

    monkeypatch.setattr(flight, "_walking_routes", record)
    merged = flight.reachable(engine, actor, grant_ft=30)
    assert calls == [True]
    assert merged


def test_walking_moves_never_receive_flying_routes(monkeypatch):
    """mode="walk" asks the walking owner once, as a walking-only query, and returns only walking routes."""
    engine = _flying_engine()
    actor = engine.state.actors[engine.state.current_actor_id]
    calls = []
    original = flight._walking_routes

    def record(*args, **kwargs):
        calls.append(kwargs.get("flying"))
        return original(*args, **kwargs)

    monkeypatch.setattr(flight, "_walking_routes", record)
    walking = flight.reachable(engine, actor, grant_ft=30, mode="walk")
    assert calls == [False]
    assert walking
    assert all(route[2] == "walk" for route in walking.values())


def test_a_ground_walker_default_equals_its_walking_mode(tmp_path):
    """Default-inert: with no flying and no scoped walking, the merged answer is the walking answer."""
    engine = fight(tmp_path)
    actor = engine.state.actors[OWNER]
    assert not actor.position.z
    assert flight.reachable(engine, actor) == flight.reachable(engine, actor, mode="walk")

