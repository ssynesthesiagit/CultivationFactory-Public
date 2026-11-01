"""MAINREDMISC7F2: a creature can target a solid wall/object cell at its near face.

Engine rule (combat/sight_lines.py clear/hit, near_endpoint=True, aa700fb3): the
occupied endpoint cell of a BLOCKED source is exempt for creature sight, so a
wall cell is visible from outside, a second wall cell in front of it still
blocks, and the cell behind stays hidden. Effect/projectile queries keep the
exact geometry (near_endpoint=False) and the wall still blocks them.
Synthetic grids only; no fixtures.
"""
from combat import sight_lines
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position


def solid_grid(cells, width=10, height=10):
    return SquareGrid({'width_squares': width, 'height_squares': height, 'square_size_ft': 5, 'starting_positions': {},
                       'terrain_regions': [{'terrain_type': 'BLOCKED', 'movement_cost': 0, 'height_ft': 20,
                                            'cells': [{'x': x, 'y': y} for x, y in cells]}]})


def creature_sees(grid, start, end):
    return grid.line_of_sight(Position(x=start[0], y=start[1]), Position(x=end[0], y=end[1]))


def test_solid_wall_cell_is_targetable_from_outside_and_the_cell_behind_stays_hidden():
    grid = solid_grid([(4, 4)])
    assert creature_sees(grid, (0, 4), (4, 4))
    assert not creature_sees(grid, (0, 4), (5, 4))


def test_second_wall_cell_in_front_still_blocks_the_barrier_behind_it():
    grid = solid_grid([(2, 4), (3, 4), (4, 4)])
    assert creature_sees(grid, (0, 4), (2, 4))      # near face of the front cell
    assert not creature_sees(grid, (0, 4), (3, 4))  # intervening wall cell blocks
    assert not creature_sees(grid, (0, 4), (4, 4))  # cell behind stays hidden


def test_effect_and_projectile_rays_keep_the_exact_wall_geometry():
    grid = solid_grid([(4, 4)])
    start, end = Position(x=0, y=4), Position(x=4, y=4)
    assert sight_lines.clear(grid, start, end, near_endpoint=True)
    assert not sight_lines.clear(grid, start, end, near_endpoint=False)
    assert not sight_lines.clear(grid, start, end, physical=True, near_endpoint=False)
