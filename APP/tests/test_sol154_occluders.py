"""Terrain crosses: shared geometry, bamboo table queries and saved policy."""
import json
import subprocess

import pytest

from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.gate4_persistence import Gate4Persistence
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import normalize_map, to_battlefield, BAMBOO
from combat.terrain_occlusion import CELL_POLICY, CROSS_POLICY, cross_hit, saved_policy
from tests.h1_support import ROOT


def grid(cells=((2, 2),), mode='centerline', kind='SIGHT_BLOCKED', **span):
    return SquareGrid({'width_squares':8,'height_squares':8,'square_size_ft':5,
        'starting_positions':{}, 'terrain_regions':[{'terrain_type':kind,
        'occluder':mode, 'movement_cost':1, 'cells':[{'x':x,'y':y} for x,y in cells], **span}]})


def p(x,y,z=0):
    return Position(x=x,y=y,z=z)


@pytest.mark.parametrize('a,b,blocked', [
    ((0,2),(5,2),True), ((2,0),(2,5),True), ((0,0),(5,5),True),
    ((0,0),(4,3),False),  # the corner of (1,0), not its cross
])
def test_integer_cross_intersection(a,b,blocked):
    cell=(1,0) if not blocked else (2,2)
    assert cross_hit(p(*a),p(*b),cell,0,None) is blocked
    assert cross_hit(p(*b),p(*a),cell,0,None) is blocked


def test_isolated_endpoints_diagonal_join_solid_and_dynamic_obscurement():
    g=grid()
    assert not g.line_of_sight(p(0,2),p(5,2))
    assert g.line_of_sight(p(0,2),p(2,2))  # see the near side/occupant; no invented heavy obscurity
    assert g.line_of_sight(p(2,2),p(5,2))
    assert not g.line_of_sight(p(0,2),p(2,2),obscured_cells={(2,2)})
    assert not grid(((1,0),(1,1))).line_of_sight(p(0,0),p(2,1))  # joined cross tips
    assert not grid(kind='BLOCKED',mode='cell').line_of_sight(p(0,2),p(5,2))
    assert grid(kind='BLOCKED').terrain_at((2,2),'BLOCKED')  # movement stays solid


def test_height_at_actual_crossing_not_rounded_voxel():
    g=grid(height_ft=10)
    assert not g.line_of_sight(p(0,2,0),p(4,2,3))  # 7.5 ft at cross
    assert not g.line_of_sight(p(0,2,0),p(4,2,4))  # parallel arm enters at 7.5 ft before midpoint's 10 ft
    assert g.line_of_sight(p(0,0,0),p(4,4,4))  # both arms meet only at their exclusive 10-ft top
    raised=grid(height_ft=5,base_altitude_ft=10)
    assert raised.line_of_sight(p(0,2),p(4,2))
    assert not raised.line_of_sight(p(0,2,2),p(4,2,2))
    assert not grid(height_ft=8).line_of_sight(p(0,2,0),p(4,2,3))  # actual 7.5 ft, not rounded 10 ft


def test_cross_tip_in_adjacent_cell_is_symmetric_and_predecessor_is_unchanged():
    g=grid(((1,1),))
    assert not g.line_of_sight(p(0,0),p(2,1))
    assert not g.line_of_sight(p(2,1),p(0,0))
    g.bind_occluder_policy(CELL_POLICY)
    assert g.line_of_sight(p(0,0),p(2,1))  # exact historical Bresenham tie


def test_server_client_ground_geometry_parity():
    g=grid(((2,2),(3,3),(1,4)))
    points=[(x,y) for y in range(8) for x in range(8)]
    expected=[g.line_of_sight(p(*a),p(*b)) for a in points for b in points]
    script="""
    import {opacityGrid,lineOfSight} from './static/tabletop/vision.js';
    const cells=[[2,2],[3,3],[1,4]],mask=opacityGrid(8,8,[cells],cells),points=[];
    for(let y=0;y<8;y++)for(let x=0;x<8;x++)points.push([x,y]);
    process.stdout.write(JSON.stringify(points.flatMap(a=>points.map(b=>lineOfSight(8,mask,...a,...b)))));
    """
    actual=json.loads(subprocess.check_output(['node','--input-type=module','-e',script],cwd=ROOT,text=True))
    assert actual==expected


def test_geometry_cache_is_bounded_rebinds_and_does_not_cache_dynamic_rules():
    g=grid()
    a,b=p(0,0),p(4,0)
    assert g.line_of_sight(a,b)
    assert not g.line_of_sight(a,b,obscured_cells={(2,0)})
    assert g.line_of_sight(a,b)
    g.blocked.add((2,0))
    assert not g.line_of_sight(a,b)  # fresh full-cell barriers
    g.blocked.remove((2,0))
    g._centerline_sight_cache.update({('test',i):True for i in range(8192)})
    assert g.line_of_sight(p(0,1),p(4,1))
    assert len(g._centerline_sight_cache)<=8192
    g.bind_occluder_policy(CELL_POLICY)
    assert not g._centerline_sight_cache and not g.centerline_cells
    g.bind_occluder_policy(CROSS_POLICY)
    assert not g._centerline_sight_cache and g.centerline_cells


def test_cross_policy_survives_commit_and_cold_reload(tmp_path):
    from tests.persistence_support import end_turn
    arena=to_battlefield(normalize_map({'display_name':'Cross persistence','materials':[
        {'material':BAMBOO,'cells':[[x,y] for x in (3,4) for y in (3,4)]}]}))
    persistence=Gate4Persistence(ROOT,tmp_path)
    session=persistence.create_match(match_seed='SOL154-CONTINUE',battlefield=arena)
    end_turn(session)
    loaded=Gate4Persistence(ROOT,tmp_path).load_match(session.match_id)
    assert loaded.engine.grid.occluder_policy==CROSS_POLICY
    assert loaded.engine.grid.centerline_cells
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'


def test_map_modes_and_overlapping_full_wall():
    cells=[[x,y] for y in (2,3) for x in (2,3)]
    doc=normalize_map({'display_name':'Crosses','materials':[{'material':BAMBOO,'cells':cells}],
                       'trees':[{'x':5,'y':5}]})
    arena=to_battlefield(doc)
    g=SquareGrid(arena)
    assert g.centerline_cells=={tuple(c) for c in cells}|{(5,5)}
    doc['materials'][0]['occluder']='cell'
    doc['trees'][0]['occluder']='cell'
    assert not SquareGrid(to_battlefield(doc)).centerline_cells
    doc['materials'][0]['occluder']='centerline'
    doc['walls']=[{'id':'solid','shape':'rect','points':[[2,2],[3,3]],'filled':True,'blocks':'sight_and_movement'}]
    overlapped=SquareGrid(to_battlefield(doc))
    # Main keeps each height-bearing span: the solid wall must still block
    # sight and physical transmission even when bamboo shares its square.
    assert any(mode=='cell' and top is None for mode,bottom,top in overlapped.occluder_spans[(2,2)])
    assert not overlapped.line_of_sight(p(1,2),p(4,2))
    assert not overlapped.line_of_physical_transmission(p(1,2),p(4,2))
    with pytest.raises(ValueError):
        grid(mode='unknown')
    malformed=normalize_map({'materials':[None,'invalid',{'material':'floor:grass','cells':[[0,0]]}]})
    assert malformed['materials']==[{'material':'floor:grass','cells':[[0,0]]}]


@pytest.mark.parametrize('later_mode', ['centerline', None])
@pytest.mark.parametrize('empty_mode', ['cell', 'centerline'])
def test_separate_material_modes_survive_save_normalize_reload(tmp_path, later_mode, empty_mode):
    from combat.tabletop import TabletopMapStore
    left = [[x, y] for x in (2, 3) for y in (2, 3)]
    right = [[x, y] for x in (6, 7) for y in (2, 3)]
    later = {'material': BAMBOO, 'cells': right}
    if later_mode is not None:
        later['occluder'] = later_mode
    document = {'display_name': 'Separate stands', 'materials': [
        {'material': BAMBOO, 'cells': left, 'occluder': 'cell'}, later,
        {'material': BAMBOO, 'cells': [], 'occluder': empty_mode}]}
    store = TabletopMapStore(tmp_path / 'maps')
    saved = store.save(document)
    for doc in (saved, store.get(saved['map_id']), normalize_map(store.get(saved['map_id']))):
        modes = {tuple(c): row['occluder'] for row in doc['materials'] for c in row['cells']}
        assert modes == {**{tuple(c): 'cell' for c in left}, **{tuple(c): 'centerline' for c in right}}
        assert SquareGrid(to_battlefield(doc)).centerline_cells == {tuple(c) for c in right}
    assert store.save(saved)['materials'] == saved['materials']


def test_later_painting_wins_mode_only_on_its_cells():
    document = normalize_map({'materials': [
        {'material': BAMBOO, 'cells': [[2, 2], [3, 2]], 'occluder': 'cell'},
        {'material': BAMBOO, 'cells': [[3, 2], [4, 2]], 'occluder': 'centerline'},
        {'material': 'terrain:fire terrain', 'cells': [[4, 2]]}]})
    assert document['materials'] == [
        {'material': BAMBOO, 'cells': [[2, 2]], 'height_ft': 20, 'occluder': 'cell'},
        {'material': BAMBOO, 'cells': [[3, 2]], 'height_ft': 20, 'occluder': 'centerline'},
        {'material': 'terrain:fire terrain', 'cells': [[4, 2]]}]


def test_shared_ground_card_describes_bound_geometry_and_preserves_costs():
    from combat.ground_text import catalog
    script = """
    import {groundCard} from './static/tabletop/ground-text.js';
    let input=''; for await (const chunk of process.stdin) input+=chunk;
    const catalog=JSON.parse(input),cards=[];
    for (const centerline of [true,false]) for (const kind of ['screen','tree','wall']) {
      cards.push(groundCard({x:2,y:2}, {catalog,centerline,
        terrain:'bamboo thicket',difficult:true,sight:true,blocked:kind!=='screen',tree:kind==='tree'}));
    }
    console.log(JSON.stringify(cards));
    """
    cards = json.loads(subprocess.check_output(['node','--input-type=module','-e',script],
        input=json.dumps(catalog()),cwd=ROOT,text=True))
    for index, card in enumerate(cards):
        text = ' '.join(card['lines'])
        assert 'twice as much' in text
        assert 'Hidden' in text  # bamboo's existing light obscurement advice remains
        if index < 3:
            assert 'two crossing centre lines' in text
            assert 'gaps near the corners' in text and 'near side stays visible' in text
            assert 'exactly as a wall' not in text and 'nobody can attack or target' not in text
        else:
            assert 'crossing centre lines' not in text
        if index % 3 == 0:
            assert 'walk straight through' in text
        else:
            assert 'blocks movement' in text
            if index < 3:
                assert 'cannot stand' in text


def test_bamboo_road_table_perception_commit_reload_and_policy(tmp_path):
    from tests.test_save_reload_equivalence import _install_factory
    from combat import senses, target_knowledge
    ids,_=_install_factory(tmp_path,'sol154',[],None)
    combat=CombatService(ROOT,tmp_path)
    doc=json.loads((ROOT/'combat/maps/builtin-bamboo-forest-ravine.json').read_text())
    mid=combat.create_factory_match(project_ids=[ids[0].removeprefix('actor:factory.')],
        opponent_actor_ids=[ids[1]],control_modes={a:'MANUAL' for a in ids},
        arena_id='battlefield:map.'+doc['map_id'],match_seed='SOL154-BAMBOO')['match_id']
    table=TabletopService(combat,tmp_path)
    state=table.state(mid,fog=True)
    e=combat._load_session(mid).engine
    assert e.grid.centerline_cells
    assert state['terrain_occlusion_policy']==CROSS_POLICY
    for a in e.state.actors.values():
        answer=state['fog_perception'][a.entity_id]
        assert answer==senses.perception(e,a)
        assert [a.position.x,a.position.y] in answer['cells']
        for b in e.state.actors.values():
            assert (b.entity_id in answer['creatures'])==target_knowledge.can_see(e,a,b)
    # A real table transaction, then cold reload and mechanical replay.
    menu=state['menu']
    assert table.act(mid,menu['end_turn'],menu['decision_id'],menu['state_version'],state['last_sequence'],[])['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.engine.grid.occluder_policy==CROSS_POLICY
    assert loaded.engine.grid.centerline_cells==e.grid.centerline_cells
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
    fresh=TabletopService(CombatService(ROOT,tmp_path),tmp_path).state(mid,fog=True)
    assert fresh['terrain_occlusion_policy']==CROSS_POLICY


def test_unstamped_prior_genesis_rebinds_whole_cells_before_queries(tmp_path):
    # Public synthetic prior save: constructor map has new data, but unstamped
    # history must select predecessor geometry rather than today's map modes.
    arena=to_battlefield(normalize_map({'display_name':'Prior bamboo','materials':[
        {'material':BAMBOO,'cells':[[x,y] for x in (3,4) for y in (3,4)]}]}))
    persistence=Gate4Persistence(ROOT,tmp_path)
    session=persistence.create_match(match_seed='SOL154-PRIOR',battlefield=arena)
    events=[v.model_dump(mode='json') for v in session.engine.events]
    for v in events:
        v['payload'].pop('terrain_occlusion_policy',None)
    restored=persistence._engine_from_loaded(session.engine.state,events,[],commanded_cui_this_turn=False)
    assert restored.grid.occluder_policy==CELL_POLICY
    assert not restored.grid.centerline_cells
    assert saved_policy([])==CELL_POLICY
    with pytest.raises(ValueError):
        saved_policy([{'event_type':'MATCH_CREATED','payload':{'terrain_occlusion_policy':'unknown'}}])
