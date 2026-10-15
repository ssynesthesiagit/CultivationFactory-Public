"""Native Mason journey regressions; real commits, reload and replay."""
from tests.mason_native_support import *

def test_journey_native_construction_exact_hour_expiry_cold_reload(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id']
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',journey_wall_payload())
    obj=next(o for o in state['runtime_objects'].values() if not o['destroyed'])
    assert obj['current_hp']==72 and state['actors'][s.OWNER]['resources']['resource:core.qi']==29
    state=combat.journey_act(jid,state['revision'],s.OWNER,'wait',{'seconds':3599})
    loaded=CombatService(ROOT,tmp_path).journey_state(jid)
    assert not loaded['runtime_objects'][obj['object_id']]['destroyed']
    state=combat.journey_act(jid,loaded['revision'],s.OWNER,'wait',{'seconds':1})
    assert state['runtime_objects'][obj['object_id']]['destroyed']
    assert state['actors'][s.OWNER]['resources']['resource:core.qi']==29


def test_journey_objects_bind_into_native_combat_and_replay(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id']
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',journey_wall_payload())
    state=combat.journey_act(jid,state['revision'],s.OWNER,'wait',{'seconds':30})
    result=combat.journey_start_combat(jid,state['revision'],{s.OWNER:'team:a',s.FOE:'team:b',s.SECOND:'team:a'})
    engine=cold(tmp_path,result['match_id'])
    assert len(works(engine))==1 and works(engine)[0].current_hp==72
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==29


def test_journey_wrong_owner_declaration_is_atomic(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id']
    with pytest.raises(ValueError):combat.journey_act(jid,j['revision'],s.FOE,'mason_build',journey_wall_payload())
    assert combat.journey_state(jid)==j


def test_journey_return_exports_damage_and_remaining_clock_without_healing(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id']
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',journey_wall_payload())
    oid=next(iter(state['runtime_objects']))
    result=combat.journey_start_combat(jid,state['revision'],{s.OWNER:'team:a',s.FOE:'team:b',s.SECOND:'team:a'},maximum_rounds=1)
    mid=result['match_id']
    from combat.tabletop_service import TabletopService
    table=TabletopService(combat,tmp_path)
    for _ in range(12):
        engine=cold(tmp_path,mid)
        if engine.state.terminal_result is not None:break
        commit_other_table(table,mid,table.state(mid)['menu']['end_turn'])
    assert cold(tmp_path,mid).state.terminal_result is not None
    journey=combat.journey_state(jid)
    resumed=combat.journey_resume(jid,journey['revision'])
    assert not resumed['runtime_objects'][oid]['destroyed']
    assert resumed['runtime_objects'][oid]['current_hp']==cold(tmp_path,mid).state.objects[oid].current_hp
    marker=resumed['runtime_objects'][oid]['component']['asset_anchor_runtime']
    assert marker['expires_num']/marker['expires_den']<=3594
    assert CombatService(ROOT,tmp_path).journey_state(jid)==resumed
    resumed=combat.journey_act(jid,resumed['revision'],s.OWNER,'wait',{'seconds':3594})
    assert resumed['runtime_objects'][oid]['destroyed']


def test_journey_reinforcement_native_clock_and_combat_continuation(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id'];payload=journey_wall_payload()
    payload['sections'][0]['position']={'x':4,'y':5}
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    payload['sections'][0]['material_source']='terrain:'+cell_id(Position(x=4,y=5))
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',payload)
    oid=next(iter(state['runtime_objects']))
    state=combat.journey_act(jid,state['revision'],s.OWNER,'mason_reinforce',{'object_id':oid})
    assert state['runtime_objects'][oid]['ac']==17 and state['runtime_objects'][oid]['damage_threshold']==8
    result=combat.journey_start_combat(jid,state['revision'],{s.OWNER:'team:a',s.FOE:'team:b',s.SECOND:'team:a'})
    engine=cold(tmp_path,result['match_id'])
    assert engine.state.objects[oid].ac==17
    assert any(c.condition_id=='condition:typed.mason_reinforcement' for c in engine.state.actors[s.OWNER].conditions.values())


def test_journey_bastion_requires_each_native_turn_command(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id'];payload=journey_wall_payload()
    payload.update(source=BASE+'raise_the_imperial_bastion',form='Raise Sections',chosen_allies=[s.OWNER])
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',payload)
    with pytest.raises(ValueError):combat.journey_act(jid,state['revision'],s.OWNER,'wait',{'seconds':60})
    state=combat.journey_act(jid,state['revision'],s.OWNER,'wait',{'seconds':6})
    choices=combat.journey_menu(jid,s.OWNER)['options']
    assert {o['payload']['command'] for o in choices if o['kind']=='mason_command'}=={'Repair','Reconfigure','Raise New Work','Covered Advance','Brace the Defender'}
    state=combat.journey_act(jid,state['revision'],s.OWNER,'mason_command',{'command':'Brace the Defender','ally_id':s.OWNER})
    assert state['actors'][s.OWNER]['mason_command_due']==[12,1]
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state


def test_native_table_owner_scene_boundary_retires_bastion_without_qi_recovery(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id'];payload=journey_wall_payload()
    payload.update(source=BASE+'raise_the_imperial_bastion',form='Raise Sections',chosen_allies=[s.OWNER])
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',payload)
    qi=state['actors'][s.OWNER]['resources']['resource:core.qi']
    ended=combat.journey_end_scene(jid,state['revision'],'The defense ended and the party left the siege situation.')
    assert all(row['destroyed'] for row in ended['runtime_objects'].values())
    assert BASE+'raise_the_imperial_bastion' not in ended['actors'][s.OWNER]['travel_uses']
    assert ended['actors'][s.OWNER]['resources']['resource:core.qi']==qi
    assert ended['events'][-1]['kind']=='SCENE_ENDED' and ended['events'][-1]['declaration_receipt']
    assert CombatService(ROOT,tmp_path).journey_state(jid)==ended


