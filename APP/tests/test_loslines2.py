"""Line blockers: exact server rays, production fog and portable ability walls.

No browser, service restart, private owner fight or live model is used.
"""
import json
from pathlib import Path
import subprocess

import pytest


from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.sight_lines import source
from combat.terrain_occlusion import cell_span_hit, segment_clear, sight_geometry
from combat.tabletop import normalize_map, to_battlefield

APP = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_menu_embeddings(monkeypatch):
    """Keep table/reload regressions independent of the live embedding server."""
    from combat import embedding_rank, menu_rank

    def offline_transport(endpoint, body, timeout):
        raise OSError('Deterministic offline menu fixture')

    monkeypatch.setattr(menu_rank, '_CLIENT',
                        embedding_rank.EmbeddingClient(transport=offline_transport))


def node(script, data):
    result = subprocess.run(['node','--input-type=module','-e',script], cwd=APP,
                            input=json.dumps(data),text=True,capture_output=True,timeout=90)
    assert result.returncode == 0, result.stdout+result.stderr
    return json.loads(result.stdout)


def yard(cells=((4,3),(4,4),(4,5),(4,6),(4,7)), **span):
    return SquareGrid({'width_squares':12,'height_squares':12,'square_size_ft':5,
        'starting_positions':{},'terrain_regions':[{'terrain_type':'BLOCKED',
        'movement_cost':0,'cells':[{'x':x,'y':y} for x,y in cells],**span}]})


def test_near_half_caps_diagonal_peek_and_movement():
    from combat.space import SurfacePoint
    from fractions import Fraction as F
    grid=yard()
    origin=SurfacePoint(F(3,2),5,0)  # physical point (2,5.5)
    near=SurfacePoint(F(15,4),5,0)  # physical x=4.25, near half
    far=SurfacePoint(F(17,4),5,0)   # physical x=4.75, far half
    assert cell_span_hit(origin,near,(4,5),0,None), 'old square slabs hid the near face'
    assert segment_clear(grid,origin,near)
    assert not segment_clear(grid,origin,far)
    diagonal=SurfacePoint(2,2,0)
    assert segment_clear(grid,diagonal,SurfacePoint(F(15,4),3,0))
    assert not segment_clear(grid,diagonal,SurfacePoint(F(17,4),3,0))
    # Parallel diagonal entering and leaving only the near half used to hit
    # a square slab. The end cap closes a path around the centre run's tip.
    row=source([(4,y) for y in range(3,8)],'BLOCKED')
    assert row['segments']==[((9,6),(9,16)),((8,6),(10,6)),((8,16),(10,16))]
    assert not segment_clear(grid,Position(x=3,y=2),Position(x=4,y=3))
    assert grid.line_of_sight(Position(x=2,y=2),Position(x=5,y=2))
    assert not grid.line_of_sight(Position(x=2,y=5),Position(x=7,y=5))
    assert grid.terrain_at((4,5),'BLOCKED'), 'movement keeps the whole cell'


@pytest.mark.parametrize('cells', [
    [(4,y) for y in range(3,8)], [(x,4) for x in range(3,8)],
    [(4,3),(4,4),(4,6),(4,7)], [(3,3),(4,3),(4,4),(8,6)],
    [(x,y) for x in (4,5) for y in range(3,8)],
])
def test_server_client_segments_and_visible_centres_match(cells):
    grid=yard(cells)
    origin=Position(x=1,y=5)
    geometry=sight_geometry(grid)
    answer=node("""
import {readFileSync} from 'node:fs';
import {cellSegments} from './static/tabletop/sight-lines.js';
import {blockerSegments,visibilityPolygons,fogPointVisible} from './static/tabletop/fog_polygon.js';
const {cells,geometry}=JSON.parse(readFileSync(0,'utf8'));
const segments=blockerSegments({sources:geometry.lines});
const polygons=visibilityPolygons([{x:1.5,y:5.5}],segments,12,12);
console.log(JSON.stringify({segments,local:cellSegments(cells),
 visible:Array.from({length:12},(_,y)=>Array.from({length:12},(_,x)=>fogPointVisible(x+.5,y+.5,12,12,[],polygons)))}));
""",{'cells':cells,'geometry':geometry})
    expected=[[[n/2 for n in p] for p in s] for row in geometry['lines'] for s in row['segments']]
    assert answer['segments']==expected==answer['local']
    mismatches=[(x,y) for y in range(12) for x in range(12)
                if answer['visible'][y][x] != grid.line_of_sight(origin,Position(x=x,y=y))]
    assert not mismatches,mismatches


def test_map_wall_object_tree_and_raised_terrain_share_exported_geometry(tmp_path):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.test_flightsight import table_yard
    combat,table,mid,ids=table_yard(tmp_path,'object',airborne=True,altitude=16)
    initial=table.state(mid,fog=True)
    geometry=initial['fog_geometry']
    assert any(r['kind']=='BLOCKED' and r['segments'] for r in geometry['lines'])
    assert not any(r['mode']=='cell' for r in geometry['volumes'])
    menu=initial['menu']
    assert table.act(mid,menu['end_turn'],menu['decision_id'],menu['state_version'],initial['last_sequence'])['status']=='COMMITTED'
    after=TabletopService(CombatService(APP,tmp_path),tmp_path).state(mid,fog=True)
    assert after['fog_geometry']==geometry
    document=normalize_map({'display_name':'Lines','width_squares':12,'height_squares':12,
        'walls':[{'shape':'rect','points':[[4,3],[5,8]],'height_ft':10}]})
    arena=to_battlefield(document)
    grid=SquareGrid(arena)
    assert sight_geometry(grid)['lines'][0]['segments']==source([(4,y) for y in range(3,8)],'BLOCKED')['segments']
    assert grid.line_of_sight(Position(x=1,y=5,z=3),Position(x=8,y=5,z=3))
    assert not grid.line_of_sight(Position(x=1,y=5),Position(x=8,y=5))


def test_talisman_wall_maple_shrine_copy_commit_reload_and_fog(tmp_path):
    # Retain the historical test name, but its default regression is portable.
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.test_save_reload_equivalence import _install_factory
    ids, bundles = _install_factory(tmp_path, 'portable-wall', ['TAL_MAGMA_LAVA_WALL'], 'Qi')
    arena = to_battlefield(normalize_map({'width_squares':12,'height_squares':12}))
    combat = CombatService(APP,tmp_path)
    mid = combat._finish_factory_match(bundles, ids, {ids[0]:'team:a',ids[1]:'team:b'},
        {ids[0]:{'x':2,'y':6},ids[1]:{'x':9,'y':6}}, arena, [ids[0]], [ids[1]],
        control_modes={aid:'MANUAL' for aid in ids}, match_seed='PORTABLE-WALL',
        display_name='Portable wall', maximum_rounds=10)['match_id']
    table = TabletopService(combat,tmp_path)
    for _ in range(4):
        state = table.state(mid)
        menu = state['menu']
        if menu['actor_id'] == ids[0]:
            break
        assert table.act(mid,menu['end_turn'],menu['decision_id'],menu['state_version'],state['last_sequence'])['status']=='COMMITTED'
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith('Lava Wall')
                     and c.destination == Position(x=4,y=6))
    state = table.state(mid)
    assert table.act(mid,candidate.candidate_id,candidate.decision_id,candidate.state_version,state['last_sequence'])['status']=='COMMITTED'
    initial = table.state(mid,fog=True)
    wall = next(row for row in initial['fog_geometry']['lines'] if row['name']=='Lava Wall')
    assert len(wall['cells']) == 8
    assert wall['segments'] == source(wall['cells'],'BLOCKED')['segments']
    result = node("""
import {readFileSync} from 'node:fs';
import {blockerSegments,visibilityPolygons,fogPointVisible} from './static/tabletop/fog_polygon.js';
import {sightBlockerLines,blockerCellStrokes} from './static/tabletop/los-lines.js';
const {wall,zones}=JSON.parse(readFileSync(0,'utf8'));
const geometry={sources:[wall]}, segments=blockerSegments(geometry);
const polygons=visibilityPolygons([{x:2.5,y:6.5}],segments,12,12);
const strokes=[...blockerCellStrokes(sightBlockerLines(geometry,zones,null),12,12).values()].flat();
console.log(JSON.stringify({near:fogPointVisible(4.25,6.5,12,12,[],polygons),
 far:fogPointVisible(4.75,6.5,12,12,[],polygons),names:strokes.map(s=>s.name),colors:strokes.map(s=>s.color)}));
""", {'wall':wall,'zones':initial['presentation']['zones']})
    assert result['near'] and not result['far']
    assert set(result['names']) == {'Lava Wall'}
    zone = next(z for z in initial['presentation']['zones'] if z['trigger_profile'].get('name')=='Lava Wall')
    assert set(result['colors']) == {zone['trigger_profile']['color']}
    menu = initial['menu']
    assert table.act(mid,menu['end_turn'],menu['decision_id'],menu['state_version'],initial['last_sequence'])['status']=='COMMITTED'
    cold = TabletopService(CombatService(APP,tmp_path),tmp_path).state(mid,fog=True)
    assert wall in cold['fog_geometry']['lines']
