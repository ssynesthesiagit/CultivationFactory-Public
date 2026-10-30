"""Owner's Waterfall Gorge ascent through table state and production fog."""
import json
import subprocess
from pathlib import Path

import pytest

from combat.gate5_service import CombatService
from combat.canonical import canonical_sha256
from combat.tabletop_service import TabletopService
from combat.tabletop import normalize_map, to_battlefield
from tests.test_save_reload_equivalence import _install_factory

APP = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('altitude', [0, 8])
@pytest.mark.parametrize('map_name,origin,target', [
    ('builtin-realm-waterfall-gorge', (23, 32), (23, 24)),
    ('builtin-frontier-bamboo-imperial-tomb', (1, 10), (26, 5)),
])
def test_gorge_table_floor_and_client_agree_after_reload(tmp_path, altitude, map_name, origin, target):
    ids, bundles = _install_factory(tmp_path, 'altsight', [], None)
    bundles[0]['actor_template'].update(fly_speed_ft=40, hover=True)
    bundles[0].pop('bundle_sha256')
    bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])
    combat = CombatService(APP, tmp_path)
    document = normalize_map(json.loads((APP / f'combat/maps/{map_name}.json').read_text()))
    width, height = document['width_squares'], document['height_squares']
    arena = to_battlefield(document)
    mid = combat._finish_factory_match(bundles, ids,
        {ids[0]: 'team:a', ids[1]: 'team:b'},
        {ids[0]: {'x': origin[0], 'y': origin[1], 'z': altitude}, ids[1]: {'x': target[0], 'y': target[1]}},
        arena, [ids[0]], [ids[1]], control_modes={aid: 'MANUAL' for aid in ids},
        match_seed='ALTSIGHT', display_name='Altitude sight', maximum_rounds=10)['match_id']
    table = TabletopService(combat, tmp_path)
    state = table.state(mid, fog=True)
    menu = state['menu']
    assert table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'],
                     state['last_sequence'])['status'] == 'COMMITTED'
    state = TabletopService(CombatService(APP, tmp_path), tmp_path).state(mid, fog=True)
    cells = state['fog_perception'][ids[0]]['cells']
    viewer = next(a for a in state['presentation']['actors'] if a['entity_id'] == ids[0])
    assert viewer['altitude_ft'] == altitude * 5
    assert (list(target) in cells) == bool(altitude)
    script = """
import {readFileSync} from 'node:fs';
import {createTableHarness} from './tests/viewer_identity_harness.mjs';
import {fogPointVisible} from './static/tabletop/fog_polygon.js';
const {state,id,width,height}=JSON.parse(readFileSync(0,'utf8'));
const h=createTableHarness({boundIds:[id],roster:state.presentation.actors,state});
h.location.search='?match=match';
const polygons=h.fogGeometry(h.visibility()).polygons;
// Compare floor rays, separately from visible wall tops. Exercise painted
// shadows as well as the numerical sampler (which uses sampleShadows).
const floor=polygons.filter(p=>p.surface_ft===0 || p.surface_ft==null)
  .map(({covered,...p})=>p);
console.log(JSON.stringify(Array.from({length:height},(_,y)=>Array.from({length:width},(_,x)=>[
  fogPointVisible(x+.5,y+.5,width,height,[],floor),
  fogPointVisible(x+.5,y+.5,width,height,[],floor.map(({sampleShadows,...p})=>p))]))));
"""
    result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=APP,
        input=json.dumps({'state': state, 'id': ids[0], 'width': width, 'height': height}), text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    client = json.loads(result.stdout)
    seen = {tuple(c) for c in cells}
    # Ground polygons follow drawn vector boundaries. Check open ground,
    # avoiding the occupied wall cells whose top is a separate surface.
    blocked = {(c['x'], c['y']) for r in arena['terrain_regions']
               if r['terrain_type'] in {'BLOCKED', 'SIGHT_BLOCKED'} for c in r['cells']}
    mismatches = []
    for y in range(height):
        for x in range(width):
            if (x, y) not in blocked:
                # Ground vector rays have raster boundary differences at
                # cross tips. The forest ascent must agree at every center;
                # ground blocking is checked at the building target below.
                if (altitude or map_name == 'builtin-realm-waterfall-gorge') and client[y][x][0] != ((x, y) in seen):
                    mismatches.append((x, y, client[y][x], (x, y) in seen))
    assert not mismatches, (altitude, len(mismatches), mismatches[:12])
    if altitude and map_name == 'builtin-frontier-bamboo-imperial-tomb':
        # Rounded decorative silhouettes used to disagree at 105 centers,
        # including clear ground inside the upper room, at (26, 5).
        painted_mismatches = [(x, y, client[y][x], (x, y) in seen)
            for y in range(height) for x in range(width)
            if (x, y) not in blocked and client[y][x][1] != ((x, y) in seen)]
        assert not painted_mismatches, painted_mismatches[:12]
        assert not state['fog_geometry']['roofs'], 'this map has no inferred roof'
    # Canvas coverage on a mathematical boundary is a raster decision. At
    # this far ground target the painted polygon must also clear the rim.
    assert client[target[1]][target[0]] == [bool(altitude)] * 2
