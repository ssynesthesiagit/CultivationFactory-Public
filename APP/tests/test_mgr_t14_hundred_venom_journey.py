"""Outside-combat poison uses the same acquired source, native turns and replay."""
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.worker2_support import settle,reload,turn
from tests.test_mgr_t14_hundred_venom import acquire,native_exposure,commit,P,native_environment,pin_dice


def finish(table, mid, tmp_path):
    for _ in range(8):
        e=reload(tmp_path,mid)
        if e.state.terminal_result:return e
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    raise AssertionError('The bounded native scene did not finish')


def test_actual_delayed_poison_continues_through_journey_and_second_native_scene(native_environment,monkeypatch,tmp_path):
    acquire(native_environment,monkeypatch,6)
    c,_,_,owner,source,jid=native_exposure(tmp_path,native_environment,6,delivery='poisoned',stage='collected')
    state=c.journey_state(jid)
    mid=c.journey_start_scene(jid,state['revision'],{owner:'team:party',source:'team:party'})['match_id']
    table=TabletopService(c,tmp_path);turn(table,mid,source)
    before=reload(tmp_path,mid).state.actors[owner].resources['resource:core.stamina']
    prompts=commit(c,table,mid,'Recorded external exposure — resolve recorded exposure',owner,
                   {'choice:needle.swallow_the_poison_delay':['delay']})
    e=reload(tmp_path,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.swallow_the_poison_delay' for p in prompts)
    assert e.state.actors[owner].resources['resource:core.stamina']==before-1
    terminal=finish(table,mid,tmp_path)
    original=terminal.state.model_dump(mode='json')
    state=c.journey_resume(jid,c.journey_state(jid)['revision'])
    assert state['seconds']==6
    assert state['actors'][owner]['source_states'][P.removesuffix('.feature.')]['native_effects']
    # The source packet and its pending condition came from accepted native
    # actions. A time skip cannot erase them or manufacture a fresh reaction.
    with pytest.raises(ValueError,match='six-second table scene'):
        CombatService(ROOT,tmp_path).journey_act(jid,state['revision'],owner,'wait',{'seconds':60})
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state
    mid2=CombatService(ROOT,tmp_path).journey_act(jid,state['revision'],owner,'open_scene',
            {'teams':{owner:'team:party',source:'team:party'}})['match_id']
    e=reload(tmp_path,mid2)
    assert e.state.actors[owner].resources['resource:core.stamina']==before-1
    assert any(x.condition_id in ('condition:typed.swallowed_poison','condition:typed.poisoned')
               for x in e.state.actors[owner].conditions.values())
    table=TabletopService(CombatService(ROOT,tmp_path),tmp_path)
    finish(table,mid2,tmp_path)
    state=CombatService(ROOT,tmp_path).journey_resume(jid,CombatService(ROOT,tmp_path).journey_state(jid)['revision'])
    assert state['seconds']==12
    assert reload(tmp_path,mid).state.model_dump(mode='json')==original


def test_native_scene_is_explicit_and_unrelated_combat_keeps_its_team_guard(native_environment,monkeypatch,tmp_path):
    acquire(native_environment,monkeypatch,6)
    c,_,_,owner,source,jid=native_exposure(tmp_path,native_environment,6,stage='collected')
    state=c.journey_state(jid)
    with pytest.raises(ValueError,match='explicit team'):
        c.journey_start_combat(jid,state['revision'],{owner:'team:party',source:'team:party'})
    assert c.journey_state(jid)==state
    mid=c.journey_start_scene(jid,state['revision'],{owner:'team:party',source:'team:party'})['match_id']
    table=TabletopService(c,tmp_path)
    e=reload(tmp_path,mid)
    assert e.state.terminal_result is None and e.state.rules['scene_window']=='elapsed_rounds_v1'
    finish(table,mid,tmp_path)


def depleted_journey(tmp_path,env):
    c,_,_,owner,source,jid=native_exposure(tmp_path,env,6,category='acid',stage='collected')
    state=c.journey_state(jid)
    mid=c.journey_start_scene(jid,state['revision'],{owner:'party',source:'party'})['match_id']
    table=TabletopService(c,tmp_path);turn(table,mid,source)
    commit(c,table,mid,'Recorded external exposure — resolve recorded exposure',owner,
           {'reaction:typed.'+P+'swallow_the_poison':['use']})
    finish(table,mid,tmp_path)
    state=c.journey_resume(jid,c.journey_state(jid)['revision'])
    return c,jid,owner,source,state


def journey_action(c,jid,owner,kind,payload):
    state=c.journey_state(jid)
    result=c.journey_act(jid,state['revision'],owner,kind,payload)
    assert CombatService(ROOT,c.userdata_root).journey_state(jid)==result
    return result


def test_native_short_rest_quota_long_rest_and_scene_preservation(native_environment,tmp_path):
    c,jid,owner,source,state=depleted_journey(tmp_path,native_environment)
    from combat.ext.body_modes_scene_resources import AUTHORITY,RECOVERY
    initial=state['actors'][owner]['resources']['resource:core.stamina']
    assert initial==11
    scene=state['actors'][owner]['source_states'][AUTHORITY]['records']
    before=state
    with pytest.raises(ValueError):c.journey_act(jid,state['revision'],source,RECOVERY,{'phase':'start','mode':'short_rest'})
    assert c.journey_state(jid)==before
    for use in range(2):
        state=journey_action(c,jid,owner,RECOVERY,{'phase':'start','mode':'short_rest'})
        before=state
        with pytest.raises(ValueError):c.journey_act(jid,state['revision'],owner,RECOVERY,{'phase':'finish'})
        assert c.journey_state(jid)==before
        state=journey_action(c,jid,owner,'wait',{'seconds':3599})
        with pytest.raises(ValueError):c.journey_act(jid,state['revision'],owner,RECOVERY,{'phase':'finish'})
        assert c.journey_state(jid)==state
        state=journey_action(c,jid,owner,'wait',{'seconds':1})
        state=journey_action(c,jid,owner,RECOVERY,{'phase':'finish'})
        assert state['actors'][owner]['resources']['resource:core.stamina']==12
        assert state['actors'][owner]['source_states'][AUTHORITY]['recovery']['short_rests']==use+1
    with pytest.raises(ValueError):c.journey_act(jid,state['revision'],owner,RECOVERY,{'phase':'start','mode':'short_rest'})
    assert c.journey_state(jid)==state
    state=journey_action(c,jid,owner,'long_rest',{})
    assert state['actors'][owner]['source_states'][AUTHORITY]['recovery']=={'short_rests':0,'cultivation_sessions':0}
    assert state['actors'][owner]['source_states'][AUTHORITY]['records']==scene


def test_native_cultivation_requires_uninterrupted_time_and_world_authority(native_environment,tmp_path):
    c,jid,owner,source,state=depleted_journey(tmp_path,native_environment)
    from combat.ext.body_modes_scene_resources import AUTHORITY,RECOVERY
    state=journey_action(c,jid,owner,RECOVERY,{'phase':'start','mode':'cultivation_session'})
    fact={'source':AUTHORITY,'subject':owner,'kind':'recovery_interruption','scope':'actual-interruption',
          'value':{'source_rule':'A real interruption prevents this uninterrupted Body cultivation session.',
                   'source_cl':6,'interrupted':1,'reason':'The world owner records an actual interruption.'},
          'expires_at':int(state['seconds'])+7200,'readers':[owner]}
    with pytest.raises(ValueError,match='table-owner'):
        c.journey_act(jid,state['revision'],owner,'declare_fact',fact)
    assert c.journey_state(jid)==state
    state=c.journey_world_fact(jid,state['revision'],fact)
    state=journey_action(c,jid,owner,'body_source_state',{'scope':fact['scope'],'kind':fact['kind']})
    state=journey_action(c,jid,owner,'wait',{'seconds':7200})
    with pytest.raises(ValueError):c.journey_act(jid,state['revision'],owner,RECOVERY,{'phase':'finish'})
    assert c.journey_state(jid)==state
    assert state['actors'][owner]['resources']['resource:core.stamina']==11
    state=journey_action(c,jid,owner,RECOVERY,{'phase':'cancel'})
    state=journey_action(c,jid,owner,RECOVERY,{'phase':'start','mode':'cultivation_session'})
    state=journey_action(c,jid,owner,'wait',{'seconds':7199})
    with pytest.raises(ValueError):c.journey_act(jid,state['revision'],owner,RECOVERY,{'phase':'finish'})
    assert c.journey_state(jid)==state
    state=journey_action(c,jid,owner,'wait',{'seconds':1})
    state=journey_action(c,jid,owner,RECOVERY,{'phase':'finish'})
    assert state['actors'][owner]['resources']['resource:core.stamina']==12
    assert state['actors'][owner]['source_states'][AUTHORITY]['recovery']['cultivation_sessions']==1
    with pytest.raises(ValueError):c.journey_act(jid,state['revision'],owner,RECOVERY,{'phase':'start','mode':'cultivation_session'})
    assert c.journey_state(jid)==state


def test_native_realm_source_gates_furnace_and_its_type_choice_then_expires(native_environment,tmp_path,pin_dice):
    from combat.ext.body_modes_scene_resources import AUTHORITY,SUPPRESSION
    c,_,_,owner,source,jid=native_exposure(tmp_path,native_environment,18,stage='collected')
    state=c.journey_state(jid)
    fact={'source':AUTHORITY,'subject':owner,'kind':'cultivation_suppression','scope':'realm-boundary',
        'value':{'source_rule':'Body R8 Realm Suppression: effective CL limits feature access and scaling.',
                 'source_cl':20,'system':'body','effective_cl':2},'expires_at':6,'readers':[owner]}
    with pytest.raises(ValueError,match='table-owner'):c.journey_act(jid,state['revision'],owner,'declare_fact',fact)
    assert c.journey_state(jid)==state
    state=c.journey_world_fact(jid,state['revision'],fact)
    state=journey_action(c,jid,owner,'body_source_state',{'scope':fact['scope'],'kind':fact['kind']})
    mid=c.journey_start_scene(jid,state['revision'],{owner:'body',source:'other'})['match_id']
    table=TabletopService(c,tmp_path);turn(table,mid,owner)
    e=reload(tmp_path,mid)
    assert any(x.condition_id==SUPPRESSION and x.data['receipt_id'] for x in e.state.actors[owner].conditions.values())
    name=next(a.display_name for a in e.action_catalog.values() if a.owner_id==owner
        and any(x.get('attack_kind')=='unarmed' and x.get('type')=='attack' for x in ((a.parameters or {}).get('typed') or {}).get('effects',[])))
    pin_dice(e,[19]+[1]*30)
    before=e.state.actors[owner].resources['resource:core.stamina']
    prompts=commit(c,table,mid,name,source)
    assert not any('path_hit.'+P+'venom_furnace' in p['context']['reaction_source_id'] for p in prompts)
    for p in prompts:
        if p['context']['reaction_source_id']=='choice:needle.iron_fist_damage_type':
            assert 'POISON' not in {o['id'] for o in p['choice']['options']}
    assert reload(tmp_path,mid).state.actors[owner].resources['resource:core.stamina']==before
    finish(table,mid,tmp_path)
    state=c.journey_resume(jid,c.journey_state(jid)['revision'])
    assert state['seconds']==6
    mid2=c.journey_start_scene(jid,state['revision'],{owner:'body',source:'other'})['match_id']
    table=TabletopService(c,tmp_path);turn(table,mid2,owner)
    e=reload(tmp_path,mid2)
    assert not any(x.condition_id==SUPPRESSION for x in e.state.actors[owner].conditions.values())
    pin_dice(e,[19]+[1]*30)
    prompts=commit(c,table,mid2,name,source,{'choice:needle.path_hit.'+P+'venom_furnace':['Use Venom Furnace'],
        'choice:needle.sovereign_venom':['nerve','marrow'],'choice:needle.marrow_venom':['Dexterity']})
    e=reload(tmp_path,mid2)
    assert any(p['context']['reaction_source_id']=='choice:needle.path_hit.'+P+'venom_furnace' for p in prompts)
    assert e.state.actors[owner].resources['resource:core.stamina']==before-1
    assert len([x for x in e.state.actors[source].conditions.values() if x.condition_id=='condition:typed.sovereign_venom'])==2


def test_actual_brief_blood_keeps_its_creator_when_only_victim_reopens(native_environment,tmp_path,pin_dice):
    import json
    from types import SimpleNamespace
    from combat.gate2_rolls import DeterministicRollAuthority
    c,_,_,owner,source,jid=native_exposure(tmp_path,native_environment,18,stage='collected')
    state=c.journey_state(jid)
    seed='JOURNEY-'+jid+'-'+str(state['revision'])
    # Pin only native initiative draws; the source creature really takes its
    # first turn before the acquired Body character strikes it.
    pin_dice(SimpleNamespace(roller=DeterministicRollAuthority(seed)),
             [20 if aid==source else 1 for aid in state['actors']])
    mid=c.journey_start_scene(jid,state['revision'],{owner:'body',source:'other'})['match_id']
    e=reload(tmp_path,mid);assert e.state.current_actor_id==source
    table=TabletopService(c,tmp_path);turn(table,mid,owner)
    e=reload(tmp_path,mid)
    name=next(a.display_name for a in e.action_catalog.values() if a.owner_id==owner
        and any(x.get('attack_kind')=='unarmed' and x.get('type')=='attack' for x in ((a.parameters or {}).get('typed') or {}).get('effects',[])))
    # Confirmed unarmed hit, four Furnace dice, primary die, successful save,
    # then the two later missed strikes. Every draw is shared by replay.
    pin_dice(e,[19,1,1,1,1,1,20,1,1])
    commit(c,table,mid,name,source,{'choice:needle.path_hit.'+P+'venom_furnace':['Use Venom Furnace'],
        'choice:needle.sovereign_venom':['blood']})
    e=reload(tmp_path,mid)
    assert not any(x.condition_id=='condition:typed.poisoned' for x in e.state.actors[source].conditions.values())
    blood=next(x for x in e.state.actors[source].conditions.values() if x.condition_id=='condition:typed.blood_venom')
    creator=json.loads(blood.data['source_actor_snapshot'])
    assert creator['entity_id']==owner and not creator['conditions'] and not creator['action_ids']
    finish(table,mid,tmp_path)
    state=c.journey_resume(jid,c.journey_state(jid)['revision'])
    state=journey_action(c,jid,owner,'finish',{})
    arena=state['battlefield']['stable_id']
    reopened=c.create_journey(project_ids=[source.removeprefix('actor:factory.')],arena_id=arena,
        positions={source:state['actors'][source]['position']},base_paces={source:30})
    mid2=c.journey_start_scene(reopened['journey_id'],reopened['revision'],{source:'party'})['match_id']
    e=reload(tmp_path,mid2)
    assert set(e.state.actors)=={source}
    packets=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and x.source_definition_id==P+'three_sovereign_venoms']
    assert len(packets)==1 and packets[0].actor_id==owner
    assert not any(x.condition_id in ('condition:typed.blood_venom','condition:typed.sovereign_venom')
                   for x in e.state.actors[source].conditions.values())
