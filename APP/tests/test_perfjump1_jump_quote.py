"""PERFJUMP1: jump quotes are identical whether each run-up is priced once or once per candidate.

The fixture is a 10-ft roof beside a wall with a strong creature, so most run-up
prefixes support a high jump. Expected quotes were recorded from the per-candidate
pricing before the incremental change and must not move.
"""
from itertools import product

from combat import flight
from combat.gate2_runtime_models import Position
from combat import passage_routes
from tests.test_roof_movement import engine_at_wall

GOLDEN = [[0, 2, 1, [[3, 5, 0], [2, 4, 0], [1, 3, 0], [0, 2, 0], [0, 2, 1]], 20, "jump"], [0, 2, 2, [[3, 5, 0], [2, 4, 0], [1, 3, 0], [0, 2, 0], [0, 2, 1], [0, 2, 2]], 25, "jump"], [0, 5, 1, [[3, 5, 0], [2, 5, 0], [1, 5, 0], [0, 5, 0], [0, 5, 1]], 20, "jump"], [0, 5, 2, [[3, 5, 0], [2, 5, 0], [1, 5, 0], [0, 5, 0], [0, 5, 1], [0, 5, 2]], 25, "jump"], [0, 8, 1, [[3, 5, 0], [2, 6, 0], [1, 7, 0], [0, 8, 0], [0, 8, 1]], 20, "jump"], [0, 8, 2, [[3, 5, 0], [2, 6, 0], [1, 7, 0], [0, 8, 0], [0, 8, 1], [0, 8, 2]], 25, "jump"], [1, 3, 1, [[3, 5, 0], [2, 4, 0], [1, 3, 0], [1, 3, 1]], 15, "jump"], [1, 3, 2, [[3, 5, 0], [2, 4, 0], [1, 3, 0], [1, 3, 1], [1, 3, 2]], 20, "jump"], [1, 5, 1, [[3, 5, 0], [2, 5, 0], [1, 5, 0], [1, 5, 1]], 15, "jump"], [1, 5, 2, [[3, 5, 0], [2, 5, 0], [1, 5, 0], [1, 5, 1], [1, 5, 2]], 20, "jump"], [1, 7, 1, [[3, 5, 0], [2, 6, 0], [1, 7, 0], [1, 7, 1]], 15, "jump"], [1, 7, 2, [[3, 5, 0], [2, 6, 0], [1, 7, 0], [1, 7, 1], [1, 7, 2]], 20, "jump"], [2, 4, 1, [[3, 5, 0], [2, 4, 0], [2, 4, 1]], 10, "jump"], [2, 5, 1, [[3, 5, 0], [2, 5, 0], [2, 5, 1]], 10, "jump"], [2, 6, 1, [[3, 5, 0], [2, 6, 0], [2, 6, 1]], 10, "jump"], [3, 2, 1, [[3, 5, 0], [3, 4, 0], [3, 3, 0], [3, 2, 0], [3, 2, 1]], 20, "jump"], [3, 2, 2, [[3, 5, 0], [3, 4, 0], [3, 3, 0], [3, 2, 0], [3, 2, 1], [3, 2, 2]], 25, "jump"], [3, 3, 1, [[3, 5, 0], [3, 4, 0], [3, 3, 0], [3, 3, 1]], 15, "jump"], [3, 3, 2, [[3, 5, 0], [3, 4, 0], [3, 3, 0], [3, 3, 1], [3, 3, 2]], 20, "jump"], [3, 4, 1, [[3, 5, 0], [3, 4, 0], [3, 4, 1]], 10, "jump"], [3, 5, 1, [[3, 5, 0], [3, 5, 1]], 5, "jump"], [3, 6, 1, [[3, 5, 0], [3, 6, 0], [3, 6, 1]], 10, "jump"], [3, 7, 1, [[3, 5, 0], [3, 6, 0], [3, 7, 0], [3, 7, 1]], 15, "jump"], [3, 7, 2, [[3, 5, 0], [3, 6, 0], [3, 7, 0], [3, 7, 1], [3, 7, 2]], 20, "jump"], [3, 8, 1, [[3, 5, 0], [3, 6, 0], [3, 7, 0], [3, 8, 0], [3, 8, 1]], 20, "jump"], [3, 8, 2, [[3, 5, 0], [3, 6, 0], [3, 7, 0], [3, 8, 0], [3, 8, 1], [3, 8, 2]], 25, "jump"], [4, 4, 1, [[3, 5, 0], [4, 4, 0], [4, 4, 1]], 10, "jump"], [4, 5, 1, [[3, 5, 0], [4, 5, 0], [4, 5, 1]], 10, "jump"], [4, 6, 1, [[3, 5, 0], [4, 6, 0], [4, 6, 1]], 10, "jump"], [5, 3, 1, [[3, 5, 0], [4, 4, 0], [5, 3, 0], [5, 3, 1]], 15, "jump"], [5, 3, 2, [[3, 5, 0], [4, 4, 0], [5, 3, 0], [5, 3, 1], [5, 3, 2]], 20, "jump"], [5, 5, 1, [[3, 5, 0], [4, 5, 0], [5, 5, 0], [5, 5, 1]], 15, "jump"], [5, 5, 2, [[3, 5, 0], [4, 5, 0], [5, 5, 0], [5, 5, 1], [5, 5, 2]], 20, "jump"], [5, 7, 1, [[3, 5, 0], [4, 6, 0], [5, 7, 0], [5, 7, 1]], 15, "jump"], [5, 7, 2, [[3, 5, 0], [4, 6, 0], [5, 7, 0], [5, 7, 1], [5, 7, 2]], 20, "jump"], [6, 3, 2, [[3, 5, 0], [4, 4, 0], [5, 3, 0], [5, 3, 1], [5, 3, 2], [6, 3, 2]], 25, "jump"], [6, 4, 2, [[3, 5, 0], [4, 5, 0], [5, 5, 0], [5, 5, 1], [5, 5, 2], [6, 4, 2]], 25, "jump"], [6, 5, 2, [[3, 5, 0], [4, 5, 0], [5, 5, 0], [5, 5, 1], [5, 5, 2], [6, 5, 2]], 25, "jump"], [6, 6, 2, [[3, 5, 0], [4, 5, 0], [5, 5, 0], [5, 5, 1], [5, 5, 2], [6, 6, 2]], 25, "jump"], [6, 7, 2, [[3, 5, 0], [4, 6, 0], [5, 7, 0], [5, 7, 1], [5, 7, 2], [6, 7, 2]], 25, "jump"], [6, 8, 2, [[3, 5, 0], [4, 6, 0], [5, 7, 0], [5, 7, 1], [5, 7, 2], [6, 8, 2]], 25, "jump"]]


def case():
    engine, actor = engine_at_wall(wall_x=6, height_ft=10)
    actor.position = Position(x=3, y=5)
    actor.strength_score = 30
    actor.speed_ft = actor.movement_remaining_ft = 45
    origin = actor.position
    walking = {}
    for (dx, dy), length in product(((-1, 0), (1, 0), (0, -1), (0, 1), (1, 1), (1, -1), (-1, 1), (-1, -1)), (1, 2, 3)):
        path = tuple(origin.model_copy(update={'x': origin.x + dx * k, 'y': origin.y + dy * k}) for k in range(length + 1))
        if not all(0 <= p.x < engine.grid.width and 0 <= p.y < engine.grid.height for p in path):
            continue
        try:
            cost = passage_routes.path_cost(engine, actor, path, 'walk')
        except ValueError:
            continue
        walking[path[-1]] = (path, cost)
    return engine, actor, walking


def snapshot(result):
    return [[landing.x, landing.y, landing.z, [[p.x, p.y, p.z] for p in path], cost, mode]
            for landing, (path, cost, mode) in sorted(result.items(), key=lambda kv: (kv[0].x, kv[0].y, kv[0].z))]


def test_jump_candidates_and_quotes_match_recorded_per_candidate_pricing():
    engine, actor, walking = case()
    result = flight.jumps(engine, actor, walking)
    assert len(result) >= 20, 'the fixture must stay jump-heavy'
    assert snapshot(result) == GOLDEN


def test_every_jump_quote_equals_full_path_pricing():
    engine, actor, walking = case()
    for landing, (path, cost, mode) in flight.jumps(engine, actor, walking).items():
        assert path[-1] == landing
        assert cost == passage_routes.path_cost(engine, actor, path, mode)
