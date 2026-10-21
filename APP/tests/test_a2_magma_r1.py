"""Review regressions: sealed service execution, explicit choices and cold replay."""
import json
from pathlib import Path
import pytest
from combat import zones
from combat.ext import surface_areas
from combat.ext.needle import cell_id
from combat.gate2_runtime_models import Position
from combat.gate4_context import build_decision_context
from tests.test_a2_magma import MAGMA, FLOW, RIVER, SLAG, GROUND, cold, clear_arena, move_line
from tests.auto_worker1_support import LEFT, RIGHT, fight, settle, act, cell_send, turn
from tests.h1_support import ROOT


@pytest.mark.parametrize('source,name', [(FLOW,'Lava Flow'),(RIVER,'Blackglass River')])
def test_ai_service_moves_line_to_perceived_enemy(tmp_path, source, name):
    def stationary(bundle):
        if bundle['actor_template']['entity_id'] == LEFT:
            bundle['actor_template']['speed_ft'] = 0
    c,t,m = fight(tmp_path,[source],spheres=[MAGMA],arena_edit=clear_arena,
                  positions={LEFT:{'x':3,'y':6},RIGHT:{'x':8,'y':9}},bundle_edit=stationary)
    settle(cell_send(t,m,name,(8,6)))
    c,t,e = cold(c,m)
    old, = zones.typed_zones(e)
    old_cells = {(p.x,p.y,p.z) for p in old.affected_cells}
    assert (8,9,0) not in old_cells
    c.set_controller_mode(m, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    session = c._load_session(m)
    policy,_ = c.policies.for_actor(LEFT)
    context = build_decision_context(session.engine,policy,for_ai=True)
    movers = [v for v in context.legal_candidates if v.display_name == name+': move the line']
    assert movers, 'the built-in AI must receive its owned surface movement action'
    result = c.local_step(m)
    assert result['status'] == 'COMMITTED', result
    assert result['record']['selected_candidate_id'] in {v.candidate_id for v in movers}
    c,t,e = cold(c,m)
    moved, = zones.typed_zones(e)
    assert moved.zone_id == old.zone_id and moved.center != old.center
    assert (8,9,0) in {(p.x,p.y,p.z) for p in moved.affected_cells}
    assert not e.state.actors[LEFT].bonus_action_available
    assert moved.created_round == old.created_round and moved.duration_rounds == old.duration_rounds
    assert moved.per_turn_triggered == old.per_turn_triggered


def test_ai_does_not_follow_unperceived_enemy_but_player_can_move(tmp_path):
    c,t,m = fight(tmp_path,[FLOW],spheres=[MAGMA],arena_edit=clear_arena,
                  cause=[{'type':'condition','condition':'invisible','applies_to':'self','duration':'one_minute'}],
                  cause_target='SELF',positions={LEFT:{'x':3,'y':6},RIGHT:{'x':8,'y':9}})
    settle(cell_send(t,m,'Lava Flow',(8,6)))
    turn(t,m,RIGHT);settle(lambda a:act(t,m,'Cause',a));turn(t,m,LEFT)
    c,t,e = cold(c,m)
    c.set_controller_mode(m,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    session=c._load_session(m);policy,_=c.policies.for_actor(LEFT)
    context=build_decision_context(session.engine,policy,for_ai=True)
    assert not any(v.display_name=='Lava Flow: move the line' for v in context.legal_candidates)
    c.set_controller_mode(m,actor_id=LEFT,controller_mode='MANUAL')
    assert any(v['label']=='Lava Flow: move the line' for v in t.state(m)['menu']['actions'])
    _,prompts=move_line(c,t,m,'Lava Flow',(8,7))
    assert any(p['context']['reactor_id']==LEFT and p['context']['reaction_source_id']=='choice:needle.surface_destination' for p in prompts)
    cold(c,m)


@pytest.mark.parametrize('sides',[False,True])
def test_elevated_surface_sweep_requires_both_side_footprints(tmp_path,sides):
    # A sealed one-cell surface fixture exercises the shared movement seam.
    # The real Lava Flow source, concentration and compiled mover are retained.
    def tiny(bundle):
        for action in bundle['action_catalog']:
            if action['source_definition_id'].endswith(FLOW):
                typed=action['parameters']['typed']
                for key in ('area','zone_spec'):
                    typed[key].update(shape='cube',size_ft=5,width_ft=5,placed=True)
    def columns(arena):
        cells={(3,6),(4,6),(6,6),(7,7),(8,8)}
        if sides:
            cells |= {(7,6),(6,7),(8,7),(7,8)}
        arena['terrain_regions']=[{'terrain_type':'BLOCKED','height_ft':5,'movement_cost':5,
                                  'cells':[{'x':x,'y':y} for x,y in sorted(cells)]}]
    c,t,m=fight(tmp_path,[FLOW],spheres=[MAGMA],bundle_edit=tiny,arena_edit=columns,
                positions={LEFT:{'x':3,'y':6,'z':1},RIGHT:{'x':4,'y':6,'z':1}})
    settle(cell_send(t,m,'Lava Flow',(6,6)))
    c,t,e=cold(c,m)
    zone,=zones.typed_zones(e)
    assert {(p.x,p.y,p.z) for p in zone.affected_cells}=={(6,6,1)}
    action=next(a for a in e.action_catalog.values() if a.display_name=='Lava Flow: move the line')
    points=surface_areas.destinations(e,e.state.actors[LEFT],action,action.parameters['surface_translation'])
    assert ((8,8,1) in {(p.x,p.y,p.z) for p in points}) is sides
    if sides:
        def pick(p):
            wanted='cell:8,8,1'
            assert wanted in [o['id'] for o in p['choice']['options']]
            return [wanted]
        settle(lambda a:act(t,m,'Lava Flow: move the line',a),pick)
        c,t,e=cold(c,m)
        assert next(iter(zones.typed_zones(e))).center==Position(x=8,y=8,z=1)
    else:
        assert not any(g['label']=='Lava Flow: move the line' for g in t.state(m)['menu']['actions'])
        assert e.state.actors[LEFT].bonus_action_available
        cold(c,m)


@pytest.mark.parametrize('source,name,short_allowed',[(FLOW,'Lava Flow',True),(RIVER,'Blackglass River',False)])
def test_printed_translation_distance_and_manual_prompt(tmp_path,source,name,short_allowed):
    c,t,m=fight(tmp_path,[source],spheres=[MAGMA],arena_edit=clear_arena,
                positions={LEFT:{'x':3,'y':6},RIGHT:{'x':8,'y':9}})
    settle(cell_send(t,m,name,(8,6)))
    c,t,e=cold(c,m)
    state_before=e.state.model_dump(mode='json')
    question=act(t,m,name+': move the line',[])
    assert question['status']=='REACTION_REQUIRED'
    p=question['reaction'];ids={o['id'] for o in p['choice']['options']}
    assert (cell_id(Position(x=8,y=7)) in ids) is short_allowed
    assert cell_id(Position(x=8,y=8)) in ids
    assert cell_id(Position(x=8,y=9)) not in ids
    assert c._load_session(m).engine.state.model_dump(mode='json')==state_before
    text=json.dumps(p)
    assert ('up to 10 feet' in text) is short_allowed
    _,prompts=move_line(c,t,m,name,(8,8))
    assert any(p['context']['reactor_id']==LEFT for p in prompts)
    c,t,e=cold(c,m)
    assert next(iter(zones.typed_zones(e))).center==Position(x=8,y=8)


@pytest.mark.parametrize('source,name',[(SLAG,'Slag Grasp'),(GROUND,'Molten Ground'),(FLOW,'Lava Flow'),(RIVER,'Blackglass River')])
def test_single_reviewed_definition_and_service_execution(tmp_path,source,name):
    c,t,m=fight(tmp_path,[source],spheres=[MAGMA],arena_edit=clear_arena)
    if source==SLAG:
        settle(lambda a:act(t,m,name,a,target_id=RIGHT))
    else:
        settle(cell_send(t,m,name,(4,6)))
    cold(c,m)
    files=list((ROOT/'authority/typed_mechanics/reviewed_final.d').glob('*.json'))
    definitions=[p.name for p in files if source in json.loads(p.read_text()).get('mechanics',{})]
    assert definitions==['review_sw-lightning.json'], definitions
