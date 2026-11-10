import pytest

from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position


def grid():
    return SquareGrid(dict(width_squares=14, height_squares=14, square_size_ft=5,
                           starting_positions={}, terrain_regions=[]))


@pytest.mark.parametrize("goal", [(11, 5), (5, 11), (11, 8), (8, 11), (11, 11)])
def test_equal_cost_paths_hug_the_direct_line_and_agree(goal):
    g = grid()
    start, end = Position(x=2, y=2), Position(x=goal[0], y=goal[1])
    path, cost = g.shortest_path(start, end)
    assert g.reachable(start, movement_ft=100)[end] == (path, cost)
    assert cost == g.distance_ft(start, end)
    dx, dy = end.x-start.x, end.y-start.y
    assert all(abs(dx*(p.y-start.y)-dy*(p.x-start.x)) <= max(dx, dy) for p in path)


def test_horizontal_path_never_takes_a_v():
    g = grid()
    path, cost = g.shortest_path(Position(x=2, y=5), Position(x=11, y=5))
    assert {p.y for p in path} == {5}
    assert cost == 45


def test_terrain_and_blockers_preserve_cheapest_legal_route():
    g = grid()
    g.blocked = {(5, y) for y in range(6)}
    difficult = {(x, 6) for x in range(3, 9)}
    start, end = Position(x=2, y=3), Position(x=9, y=3)
    path, cost = g.shortest_path(start, end, difficult_cells=difficult)
    assert g.reachable(start, movement_ft=100, difficult_cells=difficult)[end] == (path, cost)
    assert all(g.step_legal(a, b) for a, b in zip(path, path[1:]))
    assert sum(5*g.movement_step_multiplier(a, b, difficult_cells=difficult) for a, b in zip(path, path[1:])) == cost
    assert g.shortest_path(start, end, difficult_cells=difficult, max_cost_ft=cost-1) is None
