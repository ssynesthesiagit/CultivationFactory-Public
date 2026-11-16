"""The built-in shrine pillars are solid objects with centre-plus sight."""
import copy
import json
from pathlib import Path

from combat.gate2_grid import SquareGrid
from combat.sight_lines import cross_segments
from combat.tabletop import normalize_map, to_battlefield
from combat.terrain_occlusion import CROSS_POLICY, sight_geometry


def test_shrine_pillars_bind_object_centre_pluses():
    path = Path(__file__).resolve().parents[1] / 'combat/maps/builtin-realm-maple-shrine.json'
    document = normalize_map(json.loads(path.read_text(encoding='utf-8')))
    pillars = [w for w in document['walls'] if w['id'].startswith('shrine-pillar-')]
    assert {w['id'] for w in pillars} == {f'shrine-pillar-{i}' for i in range(4)}
    arena = to_battlefield(copy.deepcopy(document))
    grid = SquareGrid(arena)
    grid.bind_occluder_policy(CROSS_POLICY)
    geometry = sight_geometry(grid)
    for wall in pillars:
        assert (wall['sight_class'], wall['occluder']) == ('object', 'centerline')
        assert wall['blocks'] == 'sight_and_movement'
        assert wall['look'] == 'red_palace'
        cell = tuple(map(int, wall['points'][0]))
        assert cell in grid.blocked
        region = next(r for r in arena['terrain_regions'] if r['region_id'] == 'wall.height.' + wall['id'])
        assert (region['sight_class'], region['occluder']) == ('object', 'centerline')
        volumes = [v for v in geometry['volumes'] if (v['x'], v['y']) == cell]
        assert any(v['mode'] == 'centerline' and v['tag'] == 'object' for v in volumes)
        assert not any(v['mode'] in ('cell', 'line') for v in volumes)
        assert grid.solid_cross_spans[cell]
        x, y = cell
        assert cross_segments([cell]) == [((2*x, 2*y+1), (2*x+2, 2*y+1)),
                                          ((2*x+1, 2*y), (2*x+1, 2*y+2))]
