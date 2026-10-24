"""Outside-combat poison uses the same acquired source, native turns and replay."""
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.worker2_support import settle,reload,turn
from tests.test_mgr_t14_hundred_venom import acquire,native_exposure,commit,P,native_environment,pin_dice,ExplicitReactions


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
    held=next(x for x in e.state.actors[owner].conditions.values() if x.condition_id=='condition:typed.swallowed_poison')
    assert held.data['expires_on'].startswith('START_OF_SLOT_AT:11:')
    terminal=finish(table,mid,tmp_path)
    import json
    original=terminal.state.model_dump(mode='json')
    state=c.journey_resume(jid,c.journey_state(jid)['revision'])
    assert state['seconds']==6
    assert state['actors'][owner]['source_states'][P.removesuffix('.feature.')].get('native_effects'),{
        'terminal_conditions':[x.model_dump(mode='json') for x in terminal.state.actors[owner].conditions.values()],
        'condition_events':[{"type":x.event_type,"source":x.source_definition_id,"actor":x.actor_id,"data":x.payload} for x in terminal.events if x.event_type in ('CONDITION_APPLIED','CONDITION_REMOVED','CONDITION_UPDATED')],
        'owned_reactions':[r.get('feature_id') for b in terminal.typed_bundle_documents if b['actor_id']==owner for r in b.get('typed_reactions',())]}
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


@pytest.mark.parametrize('defend',[False,True])
def test_actual_brief_blood_keeps_its_creator_when_only_victim_reopens(native_environment,tmp_path,pin_dice,defend):
    import json
    from types import SimpleNamespace
    from combat.gate2_rolls import DeterministicRollAuthority
    c,_,_,owner,source,jid=native_exposure(tmp_path,native_environment,18,stage='collected',source_body_cl=6 if defend else None)
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
    assert e.state.setup_tasks and e.state.actors[source].turns_started==0
    before=e.state.actors[source].resources.get('resource:core.stamina',0)
    table=TabletopService(c,tmp_path)
    setup=next(x for x in e.legal_candidates() if x.source_definition_id=='system:combat.fight_setup')
    prompts=settle(table,mid2,setup.candidate_id,
        choices=ExplicitReactions({'reaction:typed.'+P+'swallow_the_poison':['use']} if defend else {}))
    e=reload(tmp_path,mid2)
    if defend:
        assert any(p['context']['reaction_source_id']=='reaction:typed.'+P+'swallow_the_poison' for p in prompts)
        assert e.state.actors[source].resources['resource:core.stamina']==before-1
        assert not e.state.actors[source].reaction_available
        assert not any(x.condition_id=='condition:typed.venom_adaptation' for x in e.state.actors[source].conditions.values())
    packets=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and x.source_definition_id==P+'three_sovereign_venoms']
    assert len(packets)==1 and packets[0].actor_id==owner
    assert not any(x.condition_id in ('condition:typed.blood_venom','condition:typed.sovereign_venom')
                   for x in e.state.actors[source].conditions.values())


def test_zero_stamina_exhaustion_comes_from_real_guard_payments_only(native_environment,tmp_path,pin_dice):
    from combat.ext.hundred_venom_sources import FAMILY,KIND,SCOPE,COLLECT
    from combat.ext.forged_exhaustion import level
    c,_,_,owner,source,jid=native_exposure(tmp_path,native_environment,3,category='acid',amount=20,stage='collected')
    for episode in range(3):
        state=c.journey_state(jid)
        if episode:
            fact={'source':FAMILY,'subject':owner,'kind':KIND,'scope':SCOPE,'expires_at':int(state['seconds'])+120,'readers':[source],
                'value':{'name':'Recorded external exposure','source_actor':source,'delivery':'damage','category':'acid',
                         'authority':'ordinary','amount':20,'dc':16,'duration_seconds':60,'source_cl':3}}
            state=c.journey_world_fact(jid,state['revision'],fact)
            state=journey_action(c,jid,owner,COLLECT,{})
        mid=c.journey_start_scene(jid,state['revision'],{owner:'party',source:'party'})['match_id']
        table=TabletopService(c,tmp_path);turn(table,mid,source)
        pin_dice(c._load_session(mid).engine,[1]*12)
        commit(c,table,mid,'Recorded external exposure — resolve recorded exposure',owner,
               {'reaction:typed.tianxia.path.body_refining.feature.stamina_guard':['2']})
        e=reload(tmp_path,mid)
        assert e.state.actors[owner].resources['resource:core.stamina']==6-2*(episode+1)
        assert level(e.state.actors[owner])==(1 if episode==2 else 0)
        finish(table,mid,tmp_path)
        c.journey_resume(jid,c.journey_state(jid)['revision'])
    state=c.journey_state(jid)
    mid=c.journey_start_scene(jid,state['revision'],{owner:'party',source:'party'})['match_id']
    e=reload(tmp_path,mid)
    assert e.state.actors[owner].resources['resource:core.stamina']==0
    assert level(e.state.actors[owner])==1
    finish(TabletopService(c,tmp_path),mid,tmp_path)
    assert level(reload(tmp_path,mid).state.actors[owner])==1


def test_native_realm_dormancy_keeps_clocks_and_consumes_hidden_next_attack(native_environment,tmp_path,pin_dice):
    from types import SimpleNamespace
    from combat.gate2_rolls import DeterministicRollAuthority
    from combat.ext.body_modes_scene_resources import AUTHORITY,SUPPRESSION
    from combat.ext.benefit_suppression import SUPPRESSED
    from combat.ext.hundred_venom import VENOM,VENOMS
    c,_,_,owner,source,jid=native_exposure(tmp_path,native_environment,18,stage='collected')
    def start():
        state=c.journey_state(jid)
        pin_dice(SimpleNamespace(roller=DeterministicRollAuthority('JOURNEY-'+jid+'-'+str(state['revision']))),
                 [20 if aid==source else 1 for aid in state['actors']])
        mid=c.journey_start_scene(jid,state['revision'],{owner:'body',source:'other'})['match_id']
        assert reload(tmp_path,mid).state.current_actor_id==source
        return mid,TabletopService(c,tmp_path)
    def unarmed(e,aid):
        return next(a.display_name for a in e.action_catalog.values() if a.owner_id==aid
            and any(x.get('attack_kind')=='unarmed' and x.get('type')=='attack' for x in ((a.parameters or {}).get('typed') or {}).get('effects',[])))
    mid,table=start();turn(table,mid,owner)
    e=reload(tmp_path,mid);pin_dice(e,[19]+[1]*30)
    before=e.state.actors[owner].resources['resource:core.stamina']
    commit(c,table,mid,unarmed(e,owner),source,{'choice:needle.path_hit.'+P+'venom_furnace':['Use Venom Furnace'],
        'choice:needle.sovereign_venom':['nerve','blood']})
    e=reload(tmp_path,mid)
    assert {x.data['venom'] for x in e.state.actors[source].conditions.values() if x.condition_id==VENOM}=={'nerve','blood'}
    from combat.ext.hundred_venom import BLOOD
    blood=next(x for x in e.state.actors[source].conditions.values() if x.condition_id==BLOOD)
    remaining=max(0,blood.data['next_turn_at']-e.state.actors[source].turns_started)
    finish(table,mid,tmp_path)
    state=c.journey_resume(jid,c.journey_state(jid)['revision'])
    fact={'source':AUTHORITY,'subject':owner,'kind':'cultivation_suppression','scope':'dormancy',
        'value':{'source_rule':'Body R8 Realm Suppression makes already-created Sovereign Venoms dormant without refund or renewed duration.',
                 'source_cl':20,'system':'body','effective_cl':5},
        'expires_at':int(state['seconds'])+3,'readers':[owner]}
    state=c.journey_world_fact(jid,state['revision'],fact)
    journey_action(c,jid,owner,'body_source_state',{'kind':fact['kind'],'scope':fact['scope']})
    mid2,table=start();e=reload(tmp_path,mid2)
    victim=e.state.actors[source]
    assert any(x.condition_id==SUPPRESSION for x in e.state.actors[owner].conditions.values())
    hidden=[x for x in victim.conditions.values() if x.condition_id==SUPPRESSED and x.data.get('until')=='source_available']
    hidden_blood=next(x for x in hidden if x.data['model'].get('condition_id')==BLOOD)
    assert hidden_blood.data['model']['data']['next_turn_at']==victim.turns_started+remaining
    assert {x.data['model']['data']['venom'] for x in hidden if x.data['model'].get('condition_id')==VENOM}=={'nerve','blood'}
    assert not any(x.condition_id==VENOM for x in victim.conditions.values())
    assert victim.reaction_available and e._effective_speed(victim)==30
    assert e.state.actors[owner].resources['resource:core.stamina']==before-1
    pin_dice(e,[19]*30)
    commit(c,table,mid2,unarmed(e,source),owner)
    e=reload(tmp_path,mid2)
    assert any(x.event_type=='ATTACK_ROLLED' and x.actor_id==source for x in e.events)
    settle(table,mid2,table.state(mid2)['menu']['end_turn'],choices={})
    e=reload(tmp_path,mid2);victim=e.state.actors[source]
    assert e.state.current_actor_id==owner
    assert not any(x.condition_id==SUPPRESSION for x in e.state.actors[owner].conditions.values())
    markers=[x for x in victim.conditions.values() if x.condition_id==VENOM]
    assert {x.data['venom'] for x in markers}=={'nerve','blood'}
    assert {x.data['source_cl'] for x in markers}=={18}
    resumed_blood=next(x for x in victim.conditions.values() if x.condition_id==BLOOD)
    assert resumed_blood.data['next_turn_at']==victim.turns_started+remaining
    assert not victim.reaction_available and e._effective_speed(victim)==30
    assert not any(x.source_definition_id==VENOMS and x.target_field=='attack_mode' for x in victim.modifiers.values())
    finish(table,mid2,tmp_path)
    e=reload(tmp_path,mid2)
    assert not any(x.condition_id==VENOM for x in e.state.actors[source].conditions.values())
    state=c.journey_resume(jid,c.journey_state(jid)['revision'])
    assert state['seconds']==12
    assert not any(x.get('kind')=='RESOURCE_GAINED' for x in state['events'])


@pytest.mark.parametrize('disable',[0,1])
def test_native_realm_keeps_bodily_immunity_unless_source_explicitly_disables_it(native_environment,tmp_path,pin_dice,disable):
    from combat.ext.body_modes_scene_resources import AUTHORITY
    c,_,_,owner,source,jid=native_exposure(tmp_path,native_environment,18,category='ordinary_disease',delivery='save',stage='collected')
    state=c.journey_state(jid)
    fact={'source':AUTHORITY,'subject':owner,'kind':'cultivation_suppression','scope':'embodied-boundary',
        'value':{'source_rule':'Body R8 embodied durability remains during ordinary Realm Suppression; the world owner records an explicit higher source rule when it suppresses bodily traits.',
                 'source_cl':20,'system':'body','effective_cl':2,'disable_embodied_traits':disable},
        'expires_at':6,'readers':[owner]}
    state=c.journey_world_fact(jid,state['revision'],fact)
    state=journey_action(c,jid,owner,'body_source_state',{'scope':fact['scope'],'kind':fact['kind']})
    mid=c.journey_start_scene(jid,state['revision'],{owner:'body',source:'other'})['match_id']
    table=TabletopService(c,tmp_path);turn(table,mid,source)
    pin_dice(c._load_session(mid).engine,[1]*12)
    commit(c,table,mid,'Recorded external exposure — resolve recorded exposure',owner)
    e=reload(tmp_path,mid)
    assert any(x.condition_id=='condition:typed.diseased' for x in e.state.actors[owner].conditions.values()) is bool(disable)


def test_expired_native_poison_source_adapts_before_the_next_furnace(native_environment,tmp_path,pin_dice):
    from types import SimpleNamespace
    from combat.gate2_rolls import DeterministicRollAuthority
    c,_,_,owner,source,jid=native_exposure(tmp_path,native_environment,6,delivery='poisoned',stage='collected',duration_kind='current_turn_end')
    state=c.journey_state(jid)
    pin_dice(SimpleNamespace(roller=DeterministicRollAuthority('JOURNEY-'+jid+'-'+str(state['revision']))),
             [20 if aid==source else 1 for aid in state['actors']])
    mid=c.journey_start_scene(jid,state['revision'],{owner:'body',source:'other'})['match_id']
    table=TabletopService(c,tmp_path);e=reload(tmp_path,mid)
    assert e.state.current_actor_id==source
    before=e.state.actors[owner].resources['resource:core.stamina']
    commit(c,table,mid,'Recorded external exposure — resolve recorded exposure',owner,
        {'choice:needle.swallow_the_poison_delay':['delay']})
    e=reload(tmp_path,mid)
    assert not any(x.condition_id=='condition:typed.venom_adaptation' for x in e.state.actors[owner].conditions.values())
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    e=reload(tmp_path,mid)
    assert e.state.current_actor_id==owner
    stored=[x for x in e.state.actors[owner].conditions.values() if x.condition_id=='condition:typed.venom_adaptation']
    assert len(stored)==1 and stored[0].data['source_cl']==6
    assert stored[0].data['uses']==1 and stored[0].data['bonus']=='proficiency_bonus'
    assert stored[0].data['eligible_activation']==P+'venom_furnace'
    assert stored[0].data['originating_actor']==source and stored[0].data['originating_source'].startswith('source:hundred_venom.exposure.')
    assert not any(x.condition_id in ('condition:typed.poisoned','condition:typed.swallowed_poison') for x in e.state.actors[owner].conditions.values())
    assert not any(x.event_type=='CONDITION_APPLIED' and x.payload.get('condition_id')=='condition:typed.poisoned' for x in e.events)
    name=next(a.display_name for a in e.action_catalog.values() if a.owner_id==owner
        and any(x.get('type')=='attack' and x.get('attack_kind')=='unarmed' for x in ((a.parameters or {}).get('typed') or {}).get('effects',[])))
    pin_dice(c._load_session(mid).engine,[19]+[1]*25)
    commit(c,table,mid,name,source,{'choice:needle.path_hit.'+P+'venom_furnace':['Use Venom Furnace']})
    e=reload(tmp_path,mid)
    roll=next(x for x in e.events if x.event_type=='DAMAGE_ROLLED' and x.source_definition_id==P+'venom_furnace')
    assert roll.payload['modifier']==e.state.actors[owner].proficiency_bonus
    assert e.state.actors[owner].resources['resource:core.stamina']==before-2
    assert not any(x.condition_id=='condition:typed.venom_adaptation' for x in e.state.actors[owner].conditions.values())
