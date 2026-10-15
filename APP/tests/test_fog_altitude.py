"""3D table fog consumes bound heights and opaque horizontal roofs."""
import json
from fractions import Fraction
from pathlib import Path
import subprocess

import pytest

from combat import senses, target_knowledge
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.terrain_occlusion import sight_geometry, bind_roofs
from tests.test_flightsight import table_yard

APP = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('obstacle', [(15, 0), 'object'])
def test_80ft_table_sight_clears_building_and_object_after_commit_reload(tmp_path, obstacle):
    combat, table, mid, (viewer_id, target_id) = table_yard(tmp_path, obstacle, airborne=True, altitude=16)
    initial = table.state(mid, fog=True)
    assert target_id in initial['fog_perception'][viewer_id]['creatures']
    menu = initial['menu']
    assert table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'],
                     initial['last_sequence'])['status'] == 'COMMITTED'
    cold = CombatService(APP, tmp_path)
    engine = cold._load_session(mid).engine
    viewer, target = (engine.state.actors[a] for a in (viewer_id, target_id))
    assert viewer.position.z == 16
    assert target_knowledge.can_see(engine, viewer, target)
    state = TabletopService(cold, tmp_path).state(mid, fog=True)
    assert state['fog_geometry'] == sight_geometry(engine.grid)
    assert [5, 3] in state['fog_perception'][viewer_id]['cells']
    if obstacle == 'object':
        obj = next(iter(engine.state.objects.values()))
        assert obj.object_id in state['fog_perception'][viewer_id]['objects']
        assert [3,3] not in state['fog_perception'][viewer_id]['cells']
        assert senses.perceives_object(engine,viewer,obj)
    # Explicit 80-ft rays descend toward ground targets; proximity to a wall
    # still matters, so elevation must not simply disable finite obstacles.
    assert engine.grid.line_of_sight(Position(x=2, y=3, z=16), Position(x=5, y=3))
    assert not engine.grid.line_of_sight(Position(x=2, y=3), Position(x=5, y=3))


def test_roof_hides_interior_but_not_ground_beyond_or_roof_surface():
    from tests.h1_support import duel, ME
    engine = duel([])
    document = {'width_squares': 12, 'height_squares': 8,
        'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': [],
        'roof_cells': [{'x': x, 'y': 3, 'roof_top_height_ft': 23} for x in (3,4)]}
    engine.grid = SquareGrid(document)
    bind_roofs(engine.grid, document)
    viewer = engine.state.actors[ME]
    viewer.position = Position(x=1,y=3,z=16)
    assert not senses.perceives_cell(engine,viewer,Position(x=4,y=3))
    assert senses.perceives_cell(engine,viewer,Position(x=8,y=3))
    assert engine.grid.line_of_sight(Position(x=4,y=3,z=16),Position(x=4,y=3,z=5))
    assert not engine.grid.line_of_sight(Position(x=4,y=3,z=16),Position(x=4,y=3))
    assert not engine.grid.line_of_sight(Position(x=4,y=3),Position(x=4,y=3,z=16))
    # At a roof surface, looking outward/upward is clear; looking down is not.
    from combat.space import SurfacePoint
    from fractions import Fraction
    from combat.terrain_occlusion import segment_clear
    at_roof=SurfacePoint(4,3,Fraction(23,5))
    assert not segment_clear(engine.grid,at_roof,Position(x=4,y=3))
    assert segment_clear(engine.grid,at_roof,Position(x=4,y=3,z=16))
    # A ground-to-ground ray passes beneath a horizontal roof.
    assert engine.grid.line_of_sight(Position(x=1,y=3),Position(x=8,y=3))


def test_table_roof_binds_on_commit_and_cold_reload_without_revealing_interior(tmp_path):
    roofs=[{'x':x,'y':3,'roof_top_height_ft':23} for x in (4,5)]
    combat, table, mid, (viewer_id,target_id)=table_yard(tmp_path,(15,0),
        airborne=True,altitude=16,roof_cells=roofs)
    for current in (table, TabletopService(CombatService(APP,tmp_path),tmp_path)):
        state=current.state(mid,fog=True)
        assert target_id not in state['fog_perception'][viewer_id]['creatures']
        assert [5,3] not in state['fog_perception'][viewer_id]['cells']
        assert [8,3] in state['fog_perception'][viewer_id]['cells']
        assert state['fog_geometry']['roofs']==[{'x':x,'y':3,'top_ft':23} for x in (4,5)]
        menu=state['menu']
        assert current.act(mid,menu['end_turn'],menu['decision_id'],menu['state_version'],
                           state['last_sequence'])['status']=='COMMITTED'


def test_80ft_viewer_sees_tall_object_top_but_not_near_ground_behind_it(tmp_path):
    _,table,mid,(viewer_id,target_id)=table_yard(tmp_path,'tall-object',airborne=True,altitude=16)
    state=table.state(mid,fog=True)
    view=state['fog_perception'][viewer_id]
    assert target_id not in view['creatures']
    assert [5,3] not in view['cells']
    assert state['objects'][0]['id'] in view['objects']


def test_continuous_client_floor_rays_match_server_over_finite_cell_and_cross_spans():
    from tests.h1_support import duel, ME
    engine = duel([])
    document = {'width_squares': 12, 'height_squares': 8,
        'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': [
            {'terrain_type':'BLOCKED','movement_cost':0,'height_ft':15,
             'cells':[{'x':4,'y':y} for y in range(2,6)]},
            {'terrain_type':'SIGHT_BLOCKED','movement_cost':1,'height_ft':9,
             'occluder':'centerline','cells':[{'x':7,'y':y} for y in (5,6)]}],
        'roof_cells':[{'x':5,'y':3,'roof_top_height_ft':23}]}
    engine.grid = SquareGrid(document)
    bind_roofs(engine.grid, document)
    viewer=engine.state.actors[ME]
    viewer.position=Position(x=1,y=3,z=16)
    geometry=sight_geometry(engine.grid)
    script="""
import {readFileSync} from 'node:fs';
import {altitudeVisibilityPolygons} from './static/tabletop/fog-altitude.js';
import {fogPointVisible} from './static/tabletop/fog_polygon.js';
const geometry=JSON.parse(readFileSync(0,'utf8'));
const polygons=altitudeVisibilityPolygons([{position:{x:1.5,y:3.5,z:16}}],geometry,12,8)
  .filter(p=>p.surface_ft===0).map(({covered,...plane})=>plane);
console.log(JSON.stringify(Array.from({length:8},(_,y)=>Array.from({length:12},(_,x)=>
  fogPointVisible(x+.5,y+.5,12,8,[],polygons)))));
"""
    result=subprocess.run(['node','--input-type=module','-e',script],cwd=APP,
        input=json.dumps(geometry),text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stderr
    client=json.loads(result.stdout)
    expected=[[senses.perceives_cell(engine,viewer,Position(x=x,y=y))
               for x in range(12)] for y in range(8)]
    assert client==expected


def test_collinear_finite_cross_uses_its_whole_height_interval():
    from combat.terrain_occlusion import cross_hit
    a,b=Position(x=1,y=3,z=16),Position(x=11,y=3)
    assert cross_hit(a,b,(10,3),0,8)  # 8 ft at center, but 4 ft before leaving the parallel arm
    assert cross_hit(b,a,(10,3),0,8)
    assert not cross_hit(Position(x=1,y=1,z=16),Position(x=11,y=11),(10,10),0,8)


def test_surface_segment_checks_only_nearby_cells_and_matches_full_scan(monkeypatch):
    from combat import terrain_occlusion
    from combat.space import SurfacePoint

    far = [{'x': x, 'y': 15} for x in range(30)]
    grid = SquareGrid({'width_squares': 40, 'height_squares': 20, 'square_size_ft': 5,
        'starting_positions': {}, 'terrain_regions': [
            {'terrain_type': 'BLOCKED', 'movement_cost': 0, 'height_ft': 20,
             'cells': [*far, {'x': 4, 'y': 1}, {'x': 8, 'y': 1}, {'x': 12, 'y': 4}]},
            {'terrain_type': 'SIGHT_BLOCKED', 'movement_cost': 1, 'height_ft': 9,
             'occluder': 'centerline', 'cells': [{'x': 6, 'y': 1}, {'x': 10, 'y': 4}]},
        ]})

    def full_scan(start, end, *, physical=False, obscured_cells=()):
        if not physical and not terrain_occlusion.roofs_visible(grid, start, end):
            return False
        cells = grid.blocked if physical else grid.blocked | grid.opaque
        for cell in cells:
            spans = (grid.terrain_spans.get('BLOCKED', {}).get(cell,
                     [(0, grid.terrain_heights.get('BLOCKED', {}).get(cell))])
                     if physical else terrain_occlusion.cell_spans(grid, cell))
            if any(terrain_occlusion.cell_span_hit(start, end, cell, bottom, top)
                   for bottom, top in spans):
                return False
            if not physical and any(mode == 'centerline'
                    and terrain_occlusion.cross_hit(start, end, cell, bottom, top)
                    for mode, bottom, top in grid.occluder_spans.get(cell, ())):
                return False
        for cell in (() if physical else obscured_cells):
            bottom, top = ((cell[2] * 5, (cell[2] + 1) * 5)
                           if len(cell) == 3 else (0, None))
            if terrain_occlusion.cell_span_hit(start, end, cell[:2], bottom, top):
                return False
        return True

    segments = [
        (Position(x=1, y=1, z=8), Position(x=9, y=1), ()),
        (Position(x=1, y=1, z=8), Position(x=15, y=5), ((7, 3, 0),)),
        (SurfacePoint(Fraction(3, 2), Fraction(3, 2), 8),
         Position(x=9, y=4), ()),
    ]
    for start, end, obscured in segments:
        for physical in (False, True):
            expected = full_scan(start, end, physical=physical, obscured_cells=obscured)
            assert terrain_occlusion.segment_clear(
                grid, start, end, physical=physical, obscured_cells=obscured) == expected

    calls = []
    original = terrain_occlusion.cell_spans

    def counted(current_grid, cell):
        calls.append(cell)
        return original(current_grid, cell)

    monkeypatch.setattr(terrain_occlusion, 'cell_spans', counted)
    terrain_occlusion.segment_clear(grid, Position(x=1, y=1, z=8), Position(x=5, y=1))
    assert len(calls) < len(grid.blocked | grid.opaque) // 2


def test_twenty_foot_scenery_shadow_length_tracks_viewer_altitude():
    script = """
import {altitudeVisibilityPolygons} from './static/tabletop/fog-altitude.js';
const geometry={volumes:[{x:5,y:3,mode:'centerline',bottom_ft:0,top_ft:20}]};
console.log(JSON.stringify([20,40,80].map(altitude_ft=>{
  const floor=altitudeVisibilityPolygons([{altitude_ft,position:{x:1.5,y:3.5}}],geometry,20,8)
    .find(p=>p.surface_ft===0);
  return Math.max(...floor.shadows.flatMap(p=>p.map(([x])=>x)));
})));
"""
    result = subprocess.run(['node','--input-type=module','-e',script],cwd=APP,
        text=True,capture_output=True,timeout=30)
    assert result.returncode == 0, result.stderr
    top = json.loads(result.stdout)
    # At eye height equal to the blocker top, its shadow is unbounded. Above
    # it, the far edge follows d * H / (H - h) from the viewer.
    assert top[0] > 10000
    assert top[1] == pytest.approx(10.5)  # d=4.5 cells, 20 ft blocker, H=40
    assert top[2] == pytest.approx(7.5)   # d=4.5 cells, 20 ft blocker, H=80


def test_fog_geometry_uses_default_tree_height_when_map_omits_height():
    from combat.tabletop import normalize_map, to_battlefield
    document = normalize_map({'map_id':'default-tree-height','width_squares':8,'height_squares':8,
        'trees':[{'x':3,'y':3,'size':1,'look':'broadleaf'}]})
    grid = SquareGrid(to_battlefield(document))
    rows = [row for row in sight_geometry(grid)['volumes'] if (row['x'],row['y']) == (3,3)]
    assert rows and {row['top_ft'] for row in rows} == {30}


@pytest.mark.parametrize('seed', ('LOCK5-A','LOCK5-B','LOCK5-C','GATE4-TEST','GATE4-AN-1','GATE4-LEE'))
def test_six_stock_captures_unchanged(tmp_path, monkeypatch, seed):
    from tests import test_wall_height_replays as stock
    monkeypatch.setenv('WALLHEIGHT_REPLAY_EVIDENCE',str(tmp_path/'evidence'))
    stock.test_six_full_stock_ai_captures_stay_identical(tmp_path,seed)
