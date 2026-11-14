"""Route search prices a mover's occupancy and passage once, not once per step.

Why this exists: a climb route search re-ran creature_passage.volume_geometry for
every edge it tested (the occupancy rebuild in roof_movement.step_allowed and the
passage read in flight.step_cost), so one AI candidate generation cost grew with
the number of route steps. The mover's occupancy and passage cost are fixed for a
read-only search, so they are computed at the start of the search and shared by
every edge. This test counts the reads and fails if they grow with the search.
"""
from pathlib import Path

from combat import creature_passage, roof_movement
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import Position
from combat.tabletop import normalize_map, to_battlefield

ROOT = Path(__file__).resolve().parents[1]


def engine_at_wall(*, wall_x=4, climb_speed=0, height_ft=10):
    document = normalize_map({
        'display_name': 'Route search occupancy yard', 'width_squares': 18, 'height_squares': 12,
        'background': {'style': 'wood'},
        'walls': [{'shape': 'rect', 'points': [[wall_x, 3], [wall_x + 5, 8]], 'filled': False}],
        'roofs': {'height_ft': height_ft, 'climb_check': 'none'},
    })
    engine = Gate2Engine(ROOT, match_seed='route-search-occupancy', battlefield=to_battlefield(document))
    actor = engine.state.actors[engine.state.current_actor_id]
    for index, other in enumerate(engine.state.actors.values()):
        other.position = Position(x=index, y=11)
    actor.position = Position(x=wall_x - 1, y=5)
    actor.speed_ft = actor.movement_remaining_ft = 30
    actor.climb_speed_ft = climb_speed
    actor.fly_speed_ft = 0
    actor.turn_flags = {}
    return engine, actor


def test_climb_search_reads_occupancy_and_passage_once_however_many_steps(monkeypatch):
    engine, actor = engine_at_wall(climb_speed=30)
    reads = []
    real = creature_passage.volume_geometry

    def counting(*args, **kwargs):
        reads.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(creature_passage, 'volume_geometry', counting)
    routes = roof_movement.routes(engine, actor)
    # The search explores many squares; the reads must not follow them.
    assert len(routes) > 10, 'the fixture must give the search enough steps to expose a per-step read'
    assert len(reads) <= 2, f'route search read the mover occupancy/passage {len(reads)} times for {len(routes)} routes'
