"""Scenery sight geometry: a boulder/pillar/rock cell blocks sight through one invisible centre plus.

Owner 2026-10-23 (the complaint behind this): boulders showed a visible "H" of rule lines and the sight shadow
followed that H. The built-in maps author a boulder, pillar or brazier as a filled circle wall (for example
combat/maps/builtin-mountain-pass.json). combat/tabletop.py wall_sight_class resolves such a wall once: a filled
circle is a round object standing on the floor -- it keeps every movement cell and blocks sight through the shared
centre plus (cross-v1 centerline). Every other wall, round or not, keeps its footprint. The resolved 'sight_class'
and 'occluder' travel in the map/arena payload; the table and the editor read them and never infer either from a
shape, a name or a description.

The real server output of the built-in boulder map is also handed to static/tabletop/los-lines.js (the board's
renderer), which must paint no rule stroke over the boulder, keep the hover name, and still draw a wall and a door.
"""
from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.sight_lines import cross_segments
from combat.tabletop import normalize_map, to_battlefield
from combat.terrain_occlusion import CELL_POLICY, CROSS_POLICY, sight_geometry

APP = Path(__file__).resolve().parents[1]
MOUNTAIN_PASS = APP / 'combat/maps/builtin-mountain-pass.json'
BOULDER_CELLS = {(4, 8), (5, 8), (4, 9), (5, 9)}
# A ray that really enters the boulder block (cell (4, 8)) at a corner quadrant and is clear only because the
# blocker is a plus: a whole-square blocker hides it (checked against the cell-v1 policy below).
PLUS_GRAZE = ((0, 6), (7, 8))


def _document():
    return normalize_map(json.loads(MOUNTAIN_PASS.read_text(encoding='utf-8')))


def _arena():
    document = _document()
    return document, to_battlefield(copy.deepcopy(document))


def _grid(arena, policy=CROSS_POLICY):
    grid = SquareGrid(arena)
    grid.bind_occluder_policy(policy)
    return grid


def test_builtin_boulder_is_a_round_object_with_an_explicit_centre_plus():
    document, arena = _arena()
    boulder = next(wall for wall in document['walls'] if wall['id'] == 'west-boulder')
    assert boulder['sight_class'] == 'object'
    assert boulder['occluder'] == 'centerline'
    region = next(row for row in arena['terrain_regions'] if row['region_id'] == 'wall.height.west-boulder')
    assert region['occluder'] == 'centerline'
    assert region['sight_class'] == 'object'
    # A wall keeps its footprint, round or not: the authored rectangle wall is still a whole-square blocker.
    wall = next(row for row in document['walls'] if row['id'] == 'south-spur')
    assert (wall['sight_class'], wall['occluder']) == ('wall', 'cell')
    wall_region = next(row for row in arena['terrain_regions'] if row['region_id'] == 'wall.height.south-spur')
    assert wall_region['occluder'] == 'cell'
    assert wall_region['sight_class'] == 'wall'


def test_boulder_plus_blocks_its_centre_and_leaves_a_corner_grazing_ray_clear():
    _, arena = _arena()
    cross, whole = _grid(arena), _grid(arena, CELL_POLICY)
    start, end = (Position(x=PLUS_GRAZE[0][0], y=PLUS_GRAZE[0][1]),
                  Position(x=PLUS_GRAZE[1][0], y=PLUS_GRAZE[1][1]))
    # The plus still hides what is straight behind the rock.
    assert not cross.line_of_sight(Position(x=2, y=9), Position(x=8, y=9))
    # A whole square would have hidden this corner ray; the plus leaves the rock's corner art readable.
    assert not whole.line_of_sight(start, end)
    assert cross.line_of_sight(start, end)


def test_solid_round_object_blocks_movement_exactly_as_main():
    _, arena = _arena()
    cross, whole = _grid(arena), _grid(arena, CELL_POLICY)
    # Movement and its prices are the same policy answer; only sight shape changed.
    assert cross.blocked == whole.blocked
    assert cross.base_movement_cost == whole.base_movement_cost
    assert BOULDER_CELLS <= cross.blocked


def test_explicit_square_filling_wall_keeps_whole_square_sight():
    # An author who marks a round wall as a whole-square blocker (a round tower) keeps its footprint.
    document = normalize_map({'display_name': 'Round tower', 'width_squares': 8, 'height_squares': 8,
                               'walls': [{'id': 'tower', 'shape': 'circle', 'filled': True, 'blocks': 'sight_and_movement',
                                          'occluder': 'cell', 'points': [[4, 4], [5, 4]]}]})
    assert document['walls'][0]['sight_class'] == 'wall'
    assert document['walls'][0]['occluder'] == 'cell'
    grid = _grid(to_battlefield(document))
    # (0,0)->(3,4) only clips the tower's corner: a centre plus would leave it visible, a whole square hides it.
    assert not grid.line_of_sight(Position(x=0, y=0), Position(x=3, y=4))


def test_renaming_a_description_changes_no_sight_kind():
    _, arena = _arena()
    before = _geometry_identity(arena)
    renamed = copy.deepcopy(arena)
    for region in renamed['terrain_regions']:
        if region['region_id'].startswith(('wall.', 'terrain.')):
            region['description'] = 'Tall scenery: object door gate pillar rock boulder terrain'
    assert _geometry_identity(renamed) == before


def test_server_states_an_explicit_sight_shape_for_every_wall():
    document = normalize_map({'display_name': 'Plain', 'width_squares': 8, 'height_squares': 8,
                              'walls': [{'id': 'plain', 'shape': 'line', 'points': [[1, 1], [4, 1]]}]})
    assert document['walls'][0]['sight_class'] == 'wall'
    assert document['walls'][0]['occluder'] == 'cell'


def test_centre_plus_segments_are_one_cross_per_square():
    assert cross_segments([(3, 3)]) == [((6, 7), (8, 7)), ((7, 6), (7, 8))]


def test_real_builtin_map_renders_no_boulder_stroke_and_still_draws_wall_and_door(tmp_path):
    """The board's own renderer, fed the server's real output for the built-in boulder map."""
    document, arena = _arena()
    grid = _grid(arena)
    geometry = sight_geometry(grid)
    fixture = {
        'width': document['width_squares'], 'height': document['height_squares'],
        'map': document, 'regions': arena['terrain_regions'],
        'sources': grid.sight_line_sources, 'volumes': geometry['volumes'], 'roofs': geometry['roofs'],
        'boulder_cells': sorted(BOULDER_CELLS), 'wall_cells': [[11, 8]],
        'door': _door_source(),
    }
    path = tmp_path / 'scenery_sight_realmap.json'
    path.write_text(json.dumps(fixture), encoding='utf-8')
    result = subprocess.run(['node', 'tests/scenery_sight_realmap.mjs', str(path)],
                            cwd=APP, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_client_tests_for_the_stroke_rule_pass():
    result = subprocess.run(['node', '--test', 'tests/loslines_board.test.mjs', 'tests/scenery_sight_render.test.mjs',
                             'tests/scenery_sight_kind.test.mjs', 'tests/scenery_sight_fog.test.mjs'],
                            cwd=APP, text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def _geometry_identity(arena):
    """What the table reads: each source's cells and structured kind, and each plus cell's kind."""
    grid = _grid(arena)
    geometry = sight_geometry(grid)
    lines = sorted((tuple(row['cells']), row['tag']) for row in grid.sight_line_sources)
    plus = sorted((row['x'], row['y'], row.get('tag')) for row in geometry['volumes'] if row['mode'] == 'centerline')
    return lines, plus


def _door_source():
    """The source zones.sync_walls builds for a closed wooden door: whole-square, tagged door."""
    from combat.gate2_runtime_models import RuntimeObjectState
    from combat import zones
    from tests.h1_support import duel

    engine = duel([])
    door = RuntimeObjectState(object_id='object:door', object_kind='door', position=Position(x=6, y=3),
                              unattended=True, flammable=False, ac=15, current_hp=10, maximum_hp=10, height_ft=10,
                              component={'kind': 'door', 'name': 'Wooden door', 'blocks': True})
    engine.state.objects[door.object_id] = door
    zones.sync_walls(engine)
    return next(row for row in engine.grid.sight_line_sources if row['name'] == 'Wooden door')
