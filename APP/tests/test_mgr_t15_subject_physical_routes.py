"""Forced subject displacement counts physical squares, not difficult-terrain cost.

Portable: a synthetic grid with no prose, authority rows or zone indexing.
"""
from types import SimpleNamespace

from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.ext import subject_repositioning as sr


def _engine(terrain_regions):
    grid = SquareGrid({
        'width_squares': 6, 'height_squares': 3, 'square_size_ft': 5,
        'starting_positions': {}, 'terrain_regions': terrain_regions,
    })
    return SimpleNamespace(grid=grid,
        _occupied_volumes_except=lambda entity_id: set(),
        _footprint=lambda subject: None)


DIFFICULT = [{'cells': [{'x': x, 'y': 1} for x in (1, 2, 3)], 'terrain_type': 'DIFFICULT',
              'movement_cost': 3}]


def test_forced_route_crosses_difficult_terrain_within_physical_distance():
    engine = _engine(DIFFICULT)
    subject = SimpleNamespace(entity_id='subject', position=Position(x=0, y=1, z=0))
    goal = Position(x=2, y=1, z=0)
    # The forced resolver ignores terrain cost, so a 10-ft displacement must still exist.
    routes = sr.physical_routes(engine, subject, [goal], 10)
    assert (2, 1, 0) in routes
    path = [(p.x, p.y) for p in routes[(2, 1, 0)]]
    assert path[0] == (0, 1) and path[-1] == (2, 1) and len(path) == 3  # two physical squares


def test_one_square_route_preserves_selected_ground_height():
    engine = _engine([])
    start = Position(x=1, y=1, z=1)
    goal = Position(x=1, y=1, z=0)
    subject = SimpleNamespace(entity_id='subject', position=start)
    routes = sr.physical_routes(engine, subject, [goal], 5)
    assert routes[(1, 1, 0)] == (start, goal)


def test_ten_foot_route_preserves_elevated_subject_height():
    engine = _engine([])
    start = Position(x=0, y=1, z=2)
    goal = Position(x=2, y=1, z=2)
    subject = SimpleNamespace(entity_id='subject', position=start)
    routes = sr.physical_routes(engine, subject, [goal], 10)
    assert routes[(2, 1, 2)][0] == start
    assert routes[(2, 1, 2)][-1] == goal
    assert len(routes[(2, 1, 2)]) == 3


def test_terrain_cost_route_is_not_the_forced_route_budget():
    # Documents the defect: the terrain-costed search cannot reach a 10-ft square here.
    engine = _engine(DIFFICULT)
    start, goal = Position(x=0, y=1, z=0), Position(x=2, y=1, z=0)
    assert engine.grid.shortest_path(start, goal, max_cost_ft=10) is None
    assert sr.physical_routes(engine, SimpleNamespace(entity_id='s', position=start), [goal], 10)


def test_forced_route_respects_walls_and_distance_budget():
    engine = _engine([{'cells': [{'x': 1, 'y': 0}, {'x': 1, 'y': 1}, {'x': 1, 'y': 2}],
                       'terrain_type': 'BLOCKED', 'movement_cost': 1}])
    subject = SimpleNamespace(entity_id='subject', position=Position(x=0, y=1, z=0))
    routes = sr.physical_routes(engine, subject, [Position(x=2, y=1, z=0), Position(x=4, y=1, z=0)], 10)
    assert (2, 1, 0) not in routes and (4, 1, 0) not in routes
