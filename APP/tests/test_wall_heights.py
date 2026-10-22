"""Finite map scenery, roof surface data, real editor and table persistence."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from combat.map_heights import wall_height_ft
from combat.roof_coverage import roof_regions
from combat.tabletop import TabletopError, TabletopMapStore, normalize_map, to_battlefield, wall_cells

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('wall,expected', [
    ({}, 10), ({'look': 'rammed_earth'}, 10), ({'look': 'grey_brick'}, 10),
    ({'look': 'stone_rampart'}, 10), ({'kind': 'palisade'}, 10),
    ({'kind': 'building'}, 10), ({'kind': 'building', 'storeys': 3}, 30),
    ({'kind': 'fence'}, 3), ({'kind': 'low_wall'}, 3), ({'kind': 'hedge'}, 5),
    ({'look': 'bamboo_fence'}, 5), ({'look': 'ruined_stone'}, 5),
    ({'kind': 'building', 'height_ft': 27}, 27), ({'height_ft': 0}, 0),
])
def test_default_resolver(wall, expected):
    assert wall_height_ft(wall) == expected


def test_storeys_survive_normalization_and_40_foot_flight_clears_default_wall():
    from combat.gate2_runtime_models import Position
    from combat.gate2_grid import SquareGrid
    document = normalize_map({'width_squares':12, 'height_squares':8, 'walls':[
        {'shape':'rect', 'points':[[5,2],[6,3]], 'kind':'building', 'storeys':2}]})
    wall = document['walls'][0]
    assert wall['kind'] == 'building' and wall['storeys'] == 2 and wall['height_ft'] == 20
    assert normalize_map(document)['walls'] == document['walls']
    grid = SquareGrid(to_battlefield(document))
    assert grid.line_of_sight(Position(x=4,y=2,z=8), Position(x=7,y=2,z=8))
    assert not grid.line_of_sight(Position(x=4,y=2), Position(x=7,y=2))


def test_building_boundaries_and_other_props_get_finite_catalog_heights():
    document = normalize_map({'objects': [
        {'kind':kind,'x':i+1,'y':2} for i,kind in enumerate(['wall_section','door','gate','portcullis','window','crate'])]})
    for object in document['objects']:
        if object['kind'] == 'crate':
            assert object['height_ft'] == 3
        else:
            assert object['height_ft'] == 10


def test_every_shipped_wall_loads_with_finite_height_and_compiles(tmp_path):
    store = TabletopMapStore(tmp_path, ROOT / 'combat/maps')
    for path in sorted((ROOT / 'combat/maps').glob('*.json')):
        document = store.get(path.stem)
        for wall in document['walls']:
            assert type(wall['height_ft']) is int and wall['height_ft'] >= 0
        arena = to_battlefield(document)
        regions = {r['region_id']: r for r in arena['terrain_regions']}
        for wall in document['walls']:
            if wall_cells(wall, document['width_squares'], document['height_squares']):
                assert regions['wall.height.' + wall['id']]['height_ft'] == wall['height_ft']


def test_roof_coverage_matches_production_browser_geometry_for_every_builtin(tmp_path):
    store = TabletopMapStore(tmp_path, ROOT / 'combat/maps')
    maps = [store.get(p.stem) for p in sorted((ROOT / 'combat/maps').glob('*.json'))]
    script = """
import {detectRoofRegions, roofSettings} from './static/tabletop/roof-regions.js';
import {readFileSync} from 'node:fs';
const maps = JSON.parse(readFileSync(0, 'utf8'));
console.log(JSON.stringify(maps.map(d => {
  const map = {...d, width:d.width_squares, height:d.height_squares,
    floors:d.materials.filter(r=>r.material.startsWith('floor:')).map(r=>({style:r.material.slice(6),cells:r.cells}))};
  return detectRoofRegions(map).map(r=>({x:r.x,y:r.y,wall_height_ft:r.wall_height_ft,
    footprint:r.footprint.sort((a,b)=>a[1]-b[1]||a[0]-b[0]),height_ft:roofSettings(r,map.roofs).height_ft}));
})));
"""
    result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT,
                            input=json.dumps(maps), text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    browser = json.loads(result.stdout)
    for document, actual in zip(maps, browser):
        expected = [{**{k:r[k] for k in ('x','y','wall_height_ft')},
                     'footprint': [list(c) for c in sorted(r['footprint'], key=lambda c:(c[1],c[0]))],
                     'height_ft': r['wall_height_ft'] + 5} for r in roof_regions(document, wall_cells)]
        assert actual == expected, document['map_id']


def test_boundary_window_height_matches_editor_and_survives_compiled_map_reload(tmp_path):
    store = TabletopMapStore(tmp_path, ROOT / 'combat/maps')
    document = store.get('builtin-willow-village-compound')
    document['objects'].append({'id': 'tall-boundary-window', 'kind': 'window',
                                'x': 3, 'y': 4, 'axis': 'v', 'height_ft': 20})

    region = next(r for r in roof_regions(document, wall_cells) if (r['x'], r['y']) == (4, 4))
    assert region['wall_height_ft'] == 20

    script = """
import {detectRoofRegions, roofSettings} from './static/tabletop/roof-regions.js';
import {readFileSync} from 'node:fs';
const d = JSON.parse(readFileSync(0, 'utf8'));
const map = {...d, width:d.width_squares, height:d.height_squares,
  floors:d.materials.filter(r=>r.material.startsWith('floor:')).map(r=>({style:r.material.slice(6),cells:r.cells}))};
const r = detectRoofRegions(map).find(r=>r.x===4&&r.y===4);
console.log(JSON.stringify({wall_height_ft:r.wall_height_ft,height_ft:roofSettings(r,d.roofs).height_ft}));
"""
    result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT,
                            input=json.dumps(document), text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'wall_height_ft': 20, 'height_ft': 25}

    saved = store.save({**document, 'map_id': 'tall-window-roof'})
    loaded = TabletopMapStore(tmp_path, ROOT / 'combat/maps').get('tall-window-roof')
    assert saved == loaded
    assert next(o for o in loaded['objects'] if o['kind'] == 'window'
                and (o['x'], o['y']) == (3, 4))['height_ft'] == 20
    cells = {(r['x'], r['y']): r['roof_top_height_ft']
             for r in to_battlefield(loaded)['roof_cells']}
    assert cells[3, 4] == 25


@pytest.mark.parametrize('height', [True, -1, 1.5, '15'])
def test_invalid_roof_heights_are_readable_errors(height):
    for settings in [{'height_ft': height}, {'regions': [{'x': 2, 'y': 2, 'height_ft': height}]}]:
        with pytest.raises(TabletopError, match='Roof height must be a whole number'):
            normalize_map({'roofs': settings})


def test_map_height_editor_round_trip_and_open_air_coverage(tmp_path):
    store = TabletopMapStore(tmp_path, ROOT / 'combat/maps')
    document = store.get('builtin-willow-village-compound')
    document['walls'][0]['height_ft'] = 23
    document['roofs'] = {'height_ft': 25, 'regions': [{'x': 4, 'y': 4, 'height_ft': 37}]}
    saved = store.save({**document, 'map_id': 'height-copy'})
    loaded = TabletopMapStore(tmp_path, ROOT / 'combat/maps').get('height-copy')
    assert saved == loaded and loaded['walls'][0]['height_ft'] == 23
    cells = {(r['x'], r['y']): r['roof_top_height_ft'] for r in to_battlefield(loaded)['roof_cells']}
    assert cells[4, 4] == 37 and cells[15, 4] == 25
    loaded['roofs']['regions'][0]['enabled'] = False
    cells = to_battlefield(loaded)['roof_cells']
    assert not any(r['x'] == 4 and r['y'] == 4 for r in cells)
    loaded['roofs']['enabled'] = False
    assert to_battlefield(loaded)['roof_cells'] == []


def test_height_payload_survives_real_table_commit_and_cold_reload(tmp_path):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.test_builtin_arenas import _fight
    combat = CombatService(ROOT, tmp_path)
    document = combat.tabletop_maps.get('builtin-willow-village-compound')
    document['roofs'] = {'height_ft': 22, 'regions': [{'x':4, 'y':4, 'height_ft':31}]}
    combat.tabletop_maps.save({**document, 'map_id': 'height-table'})
    combat, mid = _fight(tmp_path, 'battlefield:map.height-table', size=1, rounds=1)
    table = TabletopService(combat, tmp_path)
    before = combat._load_session(mid).engine.battlefield_document
    assert before['roof_cells'] and all(type(r['roof_top_height_ft']) is int for r in before['roof_cells'])
    structures = [o for o in combat._load_session(mid).engine.state.objects.values()
                  if o.object_kind in {'wall_section','door','gate','portcullis','window'}]
    assert structures and all(o.height_ft == 10 for o in structures)
    initial = table.state(mid)
    assert table.auto_step(mid, initial['last_sequence'])['status'] == 'COMMITTED'
    cold = CombatService(ROOT, tmp_path)
    assert cold._load_session(mid).engine.battlefield_document == before
    assert TabletopService(cold, tmp_path).state(mid)['map']['roofs'] == normalize_map(document)['roofs']
    assert cold._load_session(mid).mechanical.replay()['status'] == 'PASS'


def test_production_hover_and_editor_node_checks():
    for path in ['tests/wall_height_cards.test.mjs', 'tests/wall_height_editor.test.mjs']:
        result = subprocess.run(['node', '--test', '--test-isolation=none', path], cwd=ROOT,
                                env={**os.environ}, text=True, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
