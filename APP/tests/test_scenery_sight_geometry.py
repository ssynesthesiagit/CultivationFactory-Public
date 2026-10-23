from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.tabletop import normalize_map, to_battlefield
from combat.terrain_occlusion import CROSS_POLICY
from pathlib import Path
import subprocess


APP = Path(__file__).resolve().parents[1]


def test_round_scenery_wall_uses_shared_centerline_sight_geometry():
    document = normalize_map({
        'display_name': 'Boulder sight test', 'width_squares': 8, 'height_squares': 8,
        'walls': [{'id': 'boulder', 'shape': 'circle', 'points': [[3.5, 3.5], [4, 3.5]],
                   'blocks': 'sight'}],
    })
    assert document['walls'][0]['occluder'] == 'centerline'
    arena = to_battlefield(document)
    region = next(row for row in arena['terrain_regions'] if row['region_id'] == 'wall.height.boulder')
    assert region['occluder'] == 'centerline'
    grid = SquareGrid(arena)
    grid.bind_occluder_policy(CROSS_POLICY)
    assert grid.centerline_cells == {(3, 3)}
    assert not grid.line_of_sight(Position(x=1, y=3), Position(x=6, y=3))
    assert grid.line_of_sight(Position(x=1, y=2), Position(x=6, y=2))


def test_client_renders_no_scenery_rule_strokes():
    result = subprocess.run(['node', '--test', 'tests/scenery_sight_render.test.mjs'],
                            cwd=APP, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
