"""Wall openings exercise real table actions, event replay and commit/reload."""
import pytest
import json
from pathlib import Path
import subprocess
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, to_battlefield, TabletopMapStore
from combat.tabletop_service import TabletopService
from tests.test_r3i_thread_object import _sheet
from tests.test_r3i_thread_door import _row, BUTTON
from tests.test_auto_lane1 import ROOT
from tests import test_sys_placed_effects as P


@pytest.mark.parametrize('kind', ['gate', 'window'])
@pytest.mark.parametrize('opened', [True, False])
def test_unattached_opening_editor_save_commit_reload_presentation(tmp_path, kind, opened):
    """Real editor handler -> saved map -> committed fight -> cold table token."""
    fixture = Path(__file__).with_name('doors_presentation_fixture.mjs')
    editor = subprocess.run(['node', str(fixture), 'editor', kind, str(int(opened))],
                            capture_output=True, text=True, check=True)
    store = TabletopMapStore(tmp_path / 'maps')
    saved = store.save(normalize_map(json.loads(editor.stdout)))
    document = TabletopMapStore(tmp_path / 'maps').get(saved['map_id'])
    assert document['objects'][0]['blocks'] is not opened
    owner, foe = P.ME, 'actor:factory.sol195-foe'
    bundles = [compile_character(_sheet(), actor_id=a, reaction_plan={'ask': True})
               for a in (owner, foe)]
    combat = CombatService(ROOT, tmp_path / 'combat')
    table = TabletopService(combat, tmp_path / 'combat')
    mid = combat._finish_factory_match(bundles, [owner, foe],
        {owner: 'team:a', foe: 'team:b'}, {owner: {'x':4,'y':5}, foe: {'x':10,'y':10}},
        to_battlefield(document), [owner], [foe], control_modes={owner:'MANUAL',foe:'MANUAL'},
        match_seed='SOL195-unattached', display_name='Unattached opening', maximum_rounds=5)['match_id']
    menu = table.state(mid)['menu']
    assert table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], 0)['status'] == 'COMMITTED'
    reloaded = CombatService(ROOT, tmp_path / 'combat')
    payload = TabletopService(reloaded, tmp_path / 'combat').state(mid)
    loaded = reloaded._load_session(mid)
    assert ((4,6) not in loaded.engine.grid.blocked) is opened
    assert loaded.mechanical.replay()['status'] == 'PASS'
    presentation = subprocess.run(['node', str(fixture), 'presentation', kind, str(int(opened))],
        input=json.dumps(payload['objects']), capture_output=True, text=True)
    assert presentation.returncode == 0, presentation.stderr

@pytest.mark.parametrize('mode', ['cell', 'centerline'])
@pytest.mark.parametrize('axis', ['h', 'v', 'crossing', 'partial'])
def test_door_in_wall_table_open_commit_reload(tmp_path, mode, axis):
    owner, foe = P.ME, 'actor:factory.sol195-foe'
    crossing = axis == 'crossing'
    partial = axis == 'partial'
    obstructed = crossing or partial
    axis = 'h' if obstructed else axis
    wall = {'shape':'line', 'points':[[0,6],[19,6]] if axis=='h' else [[4,0],[4,13]], 'occluder':mode}
    if crossing:
        wall['points'] = [[0,6],[12,6],[4,0],[4,12]]
    if partial:
        wall['points'] = [[0,6],[12,6],[4.5,6]]
    document=normalize_map({'display_name':'SOL195', 'width_squares':20, 'height_squares':14,
        'walls':[wall], 'objects':[_row(mount_axis=axis, mount_line=600 if axis=='h' else 400, rotation=90)]})
    store=TabletopMapStore(tmp_path/'maps')
    saved=store.save(document)
    assert TabletopMapStore(tmp_path/'maps').get(saved['map_id'])['objects']==document['objects']
    sheets=[_sheet(), _sheet()]; sheets[1]['spheres_and_talents']={}
    bundles=[compile_character(s,actor_id=a,reaction_plan={'ask':True}) for s,a in zip(sheets,[owner,foe])]
    combat=CombatService(ROOT,tmp_path/'combat'); table=TabletopService(combat,tmp_path/'combat')
    origin={'x':4,'y':5} if axis=='h' else {'x':3,'y':6}
    target=Position(x=4,y=7) if axis=='h' else Position(x=5,y=6)
    if crossing:
        origin, target = {'x':3,'y':5}, Position(x=5,y=7)
    mid=combat._finish_factory_match(bundles,[owner,foe],{owner:'team:a',foe:'team:b'},
        {owner:origin,foe:{'x':10,'y':10}},to_battlefield(document),[owner],[foe],
        control_modes={owner:'MANUAL',foe:'MANUAL'},match_seed='SOL195',display_name='Door wall',maximum_rounds=5)['match_id']
    def act(cid, answers=()):
        menu=table.state(mid)['menu']
        return table.act(mid,cid,menu['decision_id'],menu['state_version'],0,list(answers))
    for _ in range(2):
        menu=table.state(mid)['menu']
        if menu['actor_id']==owner: break
        assert act(menu['end_turn'])['status']=='COMMITTED'
    engine=combat._load_session(mid).engine
    assert (4,6) in engine.grid.blocked
    assert not engine.grid.line_of_sight(Position(**origin),target)
    assert not any(c.destination==Position(x=4,y=6) for c in engine.legal_candidates())
    candidate=next(c for c in engine.legal_candidates() if c.display_name==BUTTON)
    response=act(candidate.candidate_id)
    assert response['status']=='REACTION_REQUIRED'
    prompt=response['reaction']
    answer={**prompt['context'],'selection':'USE','option_ids':['OPEN']}
    assert act(candidate.candidate_id,[answer])['status']=='COMMITTED'
    reloaded=CombatService(ROOT,tmp_path/'combat')
    loaded=reloaded._load_session(mid)
    loaded.engine.legal_candidates()
    assert ((4,6) in loaded.engine.grid.blocked) is obstructed
    assert loaded.engine.grid.line_of_sight(Position(**origin),target) is not obstructed
    adjacent=(3,6) if axis=='h' else (4,5)
    assert adjacent in loaded.engine.grid.blocked
    obj=loaded.engine.state.objects['object:map.1']
    assert obj.component['mount_axis']==axis and obj.component['rotation']==90
    payload=TabletopService(reloaded,tmp_path/'combat').state(mid)
    door=next(o for o in payload['objects'] if o['id']=='object:map.1')
    assert door['open'] is True and door['mount_axis']==axis
    assert loaded.mechanical.replay()['status']=='PASS'
    if obstructed:
        assert not any(c.destination==Position(x=4,y=6) for c in loaded.engine.legal_candidates())
        return
    move=next(c for c in loaded.engine.legal_candidates() if c.destination==Position(x=4,y=6))
    menu=payload['menu']
    result=TabletopService(reloaded,tmp_path/'combat').act(mid,move.candidate_id,menu['decision_id'],menu['state_version'],0)
    assert result['status']=='COMMITTED'
    final=CombatService(ROOT,tmp_path/'combat')._load_session(mid)
    assert final.engine.state.actors[owner].position==Position(x=4,y=6)
    assert final.mechanical.replay()['status']=='PASS'

def test_legacy_door_does_not_cut_wall():
    from combat.tabletop import rasterize
    doc=normalize_map({'walls':[{'shape':'line','points':[[0,6],[12,6]]}], 'objects':[_row()]})
    assert (4,6) in rasterize(doc)[0]
    assert 'openings' not in to_battlefield(doc)['tabletop']

def test_opening_never_erases_an_independent_wall_or_tree():
    from combat.tabletop import rasterize
    wall={'shape':'line','points':[[0,6],[12,6]]}
    row=_row(1,mount_axis='h',mount_line=600)
    base={'walls':[wall],'objects':[row]}
    assert (4,6) not in rasterize(normalize_map(base))[0]
    crossing={'shape':'line','points':[[4,0],[4,12]]}
    assert (4,6) in rasterize(normalize_map({**base,'walls':[wall,crossing]}))[0]
    assert (4,6) in rasterize(normalize_map({**base,'trees':[{'x':4,'y':6,'size':1}]}))[0]


def test_saved_map_reuse_creates_independent_fights_and_keeps_old_arena(tmp_path):
    """Create Fight omits a seed: unchanged and re-saved maps create new snapshots."""
    from tests.run_controller_browser import PROJECTS, seed_sheets

    seed_sheets(tmp_path)
    owner, foe = ['actor:factory.' + pid for pid in PROJECTS]
    combat = CombatService(ROOT, tmp_path)
    document = combat.tabletop_maps.save(normalize_map({
        'display_name': 'Reusable door map', 'width_squares': 20, 'height_squares': 14,
        'walls': [{'shape': 'line', 'points': [[0,6],[19,6]]}],
        'objects': [_row(mount_axis='h', mount_line=600)],
        'starts': {'team1': [[4,5]], 'team2': [[10,10]]},
    }))

    def create():
        return combat.create_factory_match(
            project_ids=[PROJECTS[0]], opponent_actor_ids=[foe],
            arena_id='battlefield:map.' + document['map_id'],
            control_modes={owner: 'MANUAL', foe: 'MANUAL'},
            prefight={pid: [] for pid in PROJECTS}, maximum_rounds=5)['match_id']

    first, second = create(), create()  # same map, same roster, fresh fights
    first_path = combat._load_session(first).store.match_dir / 'Arena_Battlefield.json'
    original_bytes = first_path.read_bytes()
    document['objects'][0]['door_open'] = 1
    combat.tabletop_maps.save(document)  # re-save the SAME map, now with its door open
    third = create()
    assert len({first, second, third}) == 3
    assert first_path.read_bytes() == original_bytes
    reloaded = CombatService(ROOT, tmp_path)
    table = TabletopService(reloaded, tmp_path)
    for mid, opened in [(first, False), (second, False), (third, True)]:
        for _ in range(2):
            state = table.state(mid)
            menu = state['menu']
            if menu['actor_id'] == owner:
                break
            assert table.act(mid, menu['end_turn'], menu['decision_id'],
                             menu['state_version'], 0)['status'] == 'COMMITTED'
        assert menu['actor_id'] == owner
        assert any(move['destination'] == {'x':4, 'y':6}
                   for move in menu['moves']) is opened
        loaded = reloaded._load_session(mid)
        assert ((4,6) not in loaded.engine.grid.blocked) is opened
        assert loaded.engine.grid.line_of_sight(Position(x=4,y=5), Position(x=4,y=7)) is opened
        assert next(o for o in state['objects'] if o['id']=='object:map.1')['open'] is opened
        assert loaded.mechanical.replay()['status'] == 'PASS'
