"""Map scenery (painted terrain and placed objects) blocks sight through a centre plus by default.

Owner ruling 2026-10-23: plus symbols are the default for most objects so the object is still
visible and blocks sight. Only square-filling low walls keep full-cell sight.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from combat.gate2_grid import SquareGrid  # noqa: E402
from combat.gate2_runtime_models import Position  # noqa: E402
from combat.tabletop import normalize_map, to_battlefield  # noqa: E402
from combat.terrain_occlusion import CROSS_POLICY  # noqa: E402
from combat.sight_lines import cross_segments  # noqa: E402
from combat.ext.objects import object_occluder  # noqa: E402

BASE = {'display_name': 'plus', 'width_squares': 8, 'height_squares': 8}


def grid_for(terrain):
    grid = SquareGrid(to_battlefield(normalize_map(dict(BASE, terrain=terrain))))
    grid.bind_occluder_policy(CROSS_POLICY)
    return grid


def visible(grid, a, b):
    return grid.line_of_sight(Position(x=a[0], y=a[1]), Position(x=b[0], y=b[1]))


def test_painted_boulder_blocks_through_centre_plus_not_full_square():
    boulder = grid_for([{'type': 'SIMPLE_COVER', 'cells': [[3, 3]], 'look': 'boulder', 'height_ft': 10}])
    # (0,0)->(4,3) grazes the corner of (3,3) but crosses no centre line: a plus leaves it visible.
    assert visible(boulder, (0, 0), (4, 3))
    # The centre row is still blocked by the plus.
    assert not visible(boulder, (1, 3), (6, 3))


def test_low_wall_keeps_full_square_sight_block():
    wall = grid_for([{'type': 'SIMPLE_COVER', 'cells': [[3, 3]], 'look': 'low_wall', 'height_ft': 10}])
    assert not visible(wall, (0, 0), (4, 3))


def test_object_kinds_choose_plus_or_full_square():
    assert object_occluder('pillar') == 'centerline'
    assert object_occluder('statue') == 'centerline'
    assert object_occluder('ice_block') == 'centerline'
    assert object_occluder('wall_section') == 'cell'
    assert object_occluder('door') == 'cell'
    assert object_occluder(None) == 'cell'


def test_cross_segments_are_the_centre_plus_of_each_square():
    assert cross_segments([(3, 3)]) == [((6, 7), (8, 7)), ((7, 6), (7, 8))]
