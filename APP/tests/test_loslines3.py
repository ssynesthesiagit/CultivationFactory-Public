"""Builtin art/sight connectivity, actual culm art, fog parity and table reload.

All browser-independent; no live models. The existing LOSLINES browser script
remains opt-in for the lead's visual acceptance outside the sandbox.
"""
import json
from pathlib import Path
import subprocess

import pytest

from combat.canonical import canonical_sha256
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.scenery_sight import bamboo_culms, plant_blocks_sight, tree_trunks, trunk_cross
from combat.tabletop import BAMBOO, normalize_map, to_battlefield
from combat.terrain_occlusion import sight_geometry, segment_clear
from tests.test_loslines2 import node
from tools.check_builtin_sight import audit_maps

APP = Path(__file__).resolve().parents[1]
MAPS = sorted((APP/'combat/maps').glob('*.json'))


@pytest.mark.parametrize('name',['tests/loslines_board.test.mjs'])
def test_board_exports_every_call_tabletop_makes(name):
    # blockersAt was missing from board.js, so hover threw on screen. This runs the node board test
    # that checks each board.* call in tabletop.js is exported and hovering blocker squares is quiet.
    result=subprocess.run(['node','--test',name],cwd=APP,
                          text=True,capture_output=True,timeout=120)
    assert result.returncode==0,result.stdout+result.stderr


def test_canvas_fog_mask_regressions():
    result=subprocess.run(['node','--test','tests/fog_mask.test.mjs'],cwd=APP,
                          text=True,capture_output=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr


def test_all_builtin_art_geometry_and_markers_connect():
    results = audit_maps()
    assert len(results)==len(MAPS) and MAPS
    assert not [r for r in results if any(r[k] for k in
        ('art_without_geometry','geometry_without_art','geometry_without_marker'))]


def disagreements(client,grid,origin,w,h):
    """Cells where the client mask and the engine's creature sight disagree.

    The one documented difference is left out (MAINREDMISC7F2, a9c5bebe1; static/tabletop/fog_polygon.js header,
    pinned by tests/test_loslines3f8.py): the engine lets a creature see a solid wall or object cell at its near face
    (combat/sight_lines.py near_endpoint), while the client draws that wall as its lit edge and leaves the cell itself
    dark. Any other disagreement -- a lit cell the engine hides, or a dark cell that is not solid -- is a fog bug."""
    return [(x,y) for y in range(h) for x in range(w)
            if client[y][x]!=grid.line_of_sight(origin,Position(x=x,y=y))
            and not (not client[y][x] and (x,y) in grid.blocked)]


@pytest.mark.parametrize('path',MAPS,ids=lambda p:p.stem)
def test_builtin_client_fog_matches_engine_every_cell(path):
    doc=normalize_map(json.loads(path.read_text()))
    grid=SquareGrid(to_battlefield(doc))
    origin=next(Position(x=x,y=y) for y in range(grid.height) for x in range(grid.width)
                if (x,y) not in grid.blocked|grid.opaque)
    geometry=sight_geometry(grid)
    visible=node("""
import {readFileSync} from 'node:fs';
import {blockerSegments,visibilityPolygons,fogPointVisible} from './static/tabletop/fog_polygon.js';
const {geometry,origin,w,h}=JSON.parse(readFileSync(0,'utf8'));
// The board's own bound-fog inputs (static/tabletop/tabletop.js fogGeometry): the centre plus of every scenery
// square travels as a centerline volume, not as a line source, so the client needs both to match the engine.
const ground=(geometry.volumes||[]).filter(r=>r.mode==='centerline' && r.bottom_ft<=0 && (r.top_ft==null || r.top_ft>0));
const centerlineCells=ground.map(r=>[r.x,r.y]);
const polys=visibilityPolygons([{x:origin.x+.5,y:origin.y+.5}],blockerSegments({sources:geometry.lines,centerlineCells}),w,h);
console.log(JSON.stringify(Array.from({length:h},(_,y)=>Array.from({length:w},(_,x)=>fogPointVisible(x+.5,y+.5,w,h,[],polys)))));
""",{'geometry':geometry,'origin':origin.model_dump(),'w':grid.width,'h':grid.height})
    errors=disagreements(visible,grid,origin,grid.width,grid.height)
    assert not errors,errors[:20]


def test_size_threshold_small_shoots_and_great_tree_trunk():
    doc=normalize_map({'width_squares':10,'height_squares':10,
        'trees':[{'x':2,'y':2,'size':2},{'x':6,'y':2,'height_ft':4}],
        'materials':[{'material':BAMBOO,'cells':[[4,5]],'height_ft':20},
                     {'material':BAMBOO,'cells':[[7,7]],'height_ft':4}],
        'terrain':[{'type':'SIMPLE_COVER','look':'boulder','cells':[[5,2]]}]})
    arena=to_battlefield(doc); canonical_sha256(arena)
    grid=SquareGrid(arena)
    rows=sight_geometry(grid)['lines']
    tree=next(r for r in rows if r['name'].startswith('Tree trunk') and (2,2) in r['cells'])
    assert tree['scale']==100 and tree['segments']==[tuple(map(tuple,s)) for s in trunk_cross(tree_trunks(doc['trees'][0])[0])]
    bamboo=next(r for r in rows if r['name'].startswith('Dense bamboo') and (4,5) in r['cells'])
    assert len(bamboo['segments'])==8  # four broad stems, two tiny shoots
    assert all(isinstance(n,int) for s in bamboo['segments'] for p in s for n in p)
    assert not any(r['segments'] for r in rows if (7,7) in r['cells'] or (6,2) in r['cells'])
    assert not any((r['x'],r['y']) in {(7,7),(6,2)} for r in sight_geometry(grid)['volumes'])
    assert {(2,2),(2,3),(3,2),(3,3),(6,2)}<=grid.blocked
    assert (4,5) not in grid.blocked and (5,2) not in grid.blocked
    assert grid.terrain_at((5,2),'SIMPLE_COVER')
    assert grid.base_movement_cost[(5,2)]==1
    assert grid.base_movement_cost[(4,5)]==1
    floor=normalize_map({'width_squares':8,'height_squares':8,
        'terrain':[{'type':'DIFFICULT','height_ft':5,'cells':[[3,3]]}]})
    floor_grid=SquareGrid(to_battlefield(floor))
    assert not sight_geometry(floor_grid)['lines']
    assert floor_grid.movement_step_multiplier((2,3),(3,3))==2
    # A raised sight source cannot cast a ground shadow; the upper ray hits.
    raised=normalize_map({'width_squares':8,'height_squares':8,
        'trees':[{'x':3,'y':3,'base_altitude_ft':10,'height_ft':20}]})
    high=SquareGrid(to_battlefield(raised))
    assert segment_clear(high,Position(x=1,y=3),Position(x=6,y=3))
    assert not segment_clear(high,Position(x=1,y=3,z=3),Position(x=6,y=3,z=3))


def test_actual_bamboo_art_uses_shared_physical_centres_and_preview_marks():
    result=subprocess.run(['node','--test','tests/loslines3_art.test.mjs'],cwd=APP,
                          text=True,capture_output=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr


@pytest.mark.parametrize('altitude',[2,8,16])
def test_finite_subcell_plant_airborne_fog_matches_engine(altitude):
    doc=normalize_map({'width_squares':10,'height_squares':8,
        'trees':[{'x':4,'y':1,'size':2,'height_ft':20}],
        'materials':[{'material':BAMBOO,'cells':[[3,4]],'height_ft':20}],
        'terrain':[{'type':'SIMPLE_COVER','look':'bamboo_clump','cells':[[6,4]],'height_ft':10}]})
    grid=SquareGrid(to_battlefield(doc)); origin=Position(x=1,y=3,z=altitude)
    result=node("""
import {readFileSync} from 'node:fs';
import {altitudeVisibilityPolygons} from './static/tabletop/fog-altitude.js';
import {fogPointVisible} from './static/tabletop/fog_polygon.js';
const {geometry,z}=JSON.parse(readFileSync(0,'utf8'));
const polys=altitudeVisibilityPolygons([{position:{x:1.5,y:3.5,z}}],geometry,10,8).filter(p=>p.surface_ft===0).map(({covered,...plane})=>plane);
console.log(JSON.stringify(Array.from({length:8},(_,y)=>Array.from({length:10},(_,x)=>fogPointVisible(x+.5,y+.5,10,8,[],polys)))));
""",{'geometry':sight_geometry(grid),'z':altitude})
    errors=disagreements(result,grid,origin,10,8)
    assert not errors,errors


def test_airborne_occupied_screen_fog_matches_server_sight():
    doc=normalize_map({'width_squares':10,'height_squares':8,
        'terrain':[{'type':'SIGHT_BLOCKED','height_ft':10,'cells':[[4,4]]}]})
    grid=SquareGrid(to_battlefield(doc))
    origin=Position(x=4,y=4,z=1)  # 5 ft, inside the screen's vertical span
    result=node("""
import {readFileSync} from 'node:fs';
import {altitudeVisibilityPolygons} from './static/tabletop/fog-altitude.js';
import {fogPointVisible} from './static/tabletop/fog_polygon.js';
const {geometry}=JSON.parse(readFileSync(0,'utf8'));
const polygons=altitudeVisibilityPolygons([{position:{x:4.5,y:4.5,z:1}}],geometry,10,8)
  .filter(p=>p.surface_ft===0).map(({covered,...p})=>p);
console.log(JSON.stringify(fogPointVisible(6.5,4.5,10,8,[],polygons)));
""",{'geometry':sight_geometry(grid)})
    assert result == grid.line_of_sight(origin,Position(x=6,y=4))
    assert result is True


def test_physical_stems_survive_table_commit_and_cold_reload(tmp_path):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.test_save_reload_equivalence import _install_factory
    ids,bundles=_install_factory(tmp_path,'loslines3',[],None)
    doc=normalize_map({'map_id':'loslines3','display_name':'Stem yard','width_squares':10,'height_squares':8,
        'trees':[{'x':4,'y':1,'size':2}],
        'materials':[{'material':BAMBOO,'cells':[[3,4]],'height_ft':20}],
        'terrain':[{'type':'SIMPLE_COVER','look':'bamboo_clump','rotation':90,'cells':[[6,4]]},
                   {'type':'SIMPLE_COVER','look':'boulder','cells':[[5,6]]}],
        'objects':[{'kind':'pillar','name':'Sight pillar','x':6,'y':6}],
        'starts':{'team1':[[1,3]],'team2':[[8,3]]}})
    combat=CombatService(APP,tmp_path)
    mid=combat._finish_factory_match(bundles,ids,{ids[0]:'team:a',ids[1]:'team:b'},
        {ids[0]:{'x':1,'y':3},ids[1]:{'x':8,'y':3}},to_battlefield(doc),[ids[0]],[ids[1]],
        control_modes={aid:'MANUAL' for aid in ids},match_seed='LOSLINES3',display_name='Stem yard',maximum_rounds=10)['match_id']
    table=TabletopService(combat,tmp_path)
    first=table.state(mid,fog=True)
    assert any(r.get('scale')==100 for r in first['fog_geometry']['lines'])
    assert any(r['name']=='Sight pillar' for r in first['fog_geometry']['lines'])
    menu=first['menu']
    assert table.act(mid,menu['end_turn'],menu['decision_id'],menu['state_version'],first['last_sequence'])['status']=='COMMITTED'
    after=TabletopService(CombatService(APP,tmp_path),tmp_path).state(mid,fog=True)
    assert after['fog_geometry']==first['fog_geometry']
    canonical_sha256(after['fog_geometry'])  # persistent inputs/export are integer-safe
