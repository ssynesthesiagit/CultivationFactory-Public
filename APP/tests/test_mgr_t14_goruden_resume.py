"""Review regressions through acquired characters, native intents and cold replay."""
import json
import zipfile
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.factory_compiler import compile_character
from tests.h1_support import ROOT, sheet
from tests.test_mgr_t14_goruden_build import acquire
from tests.test_mgr_t14_goruden import prepare, use, ready
from tests.worker2_support import fixture, reload, settle, OWNER, ALLY, FOE


@pytest.mark.parametrize('collected',[False,True])
def test_fresh_and_replaced_fact_spends_combat_lifetime(catalog_environment,monkeypatch,tmp_path,collected):
    from combat.ext.goruden_journey import FIST,KIND,SCOPE,FACT,FAMILY
    acquired=acquire(catalog_environment,monkeypatch)
    owner='actor:factory.gold';foe='actor:factory.foe'
    for pid,doc in [('gold',acquired),('foe',sheet([],cl=18))]:
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    def cold():return CombatService(ROOT,tmp_path)
    cold().tabletop_maps.save({'display_name':'Gold return','width_squares':20,'height_squares':20,'terrain':[]})
    arena=next(k for k,v in cold().factory_arenas().items() if v['display_name']=='Gold return')
    state=cold().create_journey(project_ids=['gold','foe'],arena_id=arena,
        positions={owner:{'x':3,'y':6},foe:{'x':4,'y':6}},base_paces={owner:30,foe:30})
    jid=state['journey_id']
    fact={'source':FIST,'subject':foe,'kind':KIND,'scope':SCOPE,'value':1,'expires_at':6,'readers':[]}
    state=cold().journey_world_fact(jid,state['revision'],fact)
    if collected:
        state=cold().journey_act(jid,state['revision'],owner,'goruden_collect',{})
        state=cold().journey_world_fact(jid,state['revision'],fact)
    receipt=state['fact_consent_admission'][-1]['receipt_id']
    state=cold().journey_start_combat(jid,state['revision'],{owner:'team:gold',foe:'team:foe'},maximum_rounds=1)
    mid=state['match_id'];table=TabletopService(cold(),tmp_path)
    e=reload(tmp_path,mid)
    assert any(c.condition_id==FACT and c.data['receipt_id']==receipt for c in e.state.actors[foe].conditions.values())
    for _ in range(8):
        if reload(tmp_path,mid).state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path,mid).state.terminal_result is not None
    state=cold().journey_resume(jid,cold().journey_state(jid)['revision'])
    assert state['seconds']==0
    saved=state['actors'][foe]['source_states'][FAMILY]
    assert saved['fact_remaining_num']==0
    assert cold().journey_verify(jid)['status']=='PASS'
    assert json.loads(saved['fact_record'])['receipt_id']==receipt
    state=cold().journey_start_combat(jid,state['revision'],{owner:'team:gold',foe:'team:foe'},maximum_rounds=1)
    assert not any(c.condition_id==FACT for c in reload(tmp_path,state['match_id']).state.actors[foe].conditions.values())


def test_acquired_commands_reach_ai_and_finish_free_preparation(catalog_environment,monkeypatch,tmp_path):
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary
    bundle=compile_character(acquire(catalog_environment,monkeypatch),actor_id=OWNER,reaction_plan={'ask':True})
    c,t,m=fixture(tmp_path,[],owner_bundle=bundle,bundle_transform=prepare,
                   positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':3,'y':7}})
    def options():
        e=reload(tmp_path,m)
        policy=PolicyLibrary(ROOT).for_actor(OWNER)[0]
        context=build_decision_context(e,policy,for_ai=True)
        return {e.action_catalog[x.source_definition_id].display_name for x in context.legal_candidates if x.source_definition_id in e.action_catalog}
    assert 'Golden Sheen: Suppress visible gold' in options()
    use(c,t,m,'Golden Sheen: Suppress visible gold')
    assert not any(n.startswith('Golden Sheen:') and 'Intimidation' not in n for n in options())
    use(c,t,m,'Golden Aura',picks={'choice:needle.goruden.aura_ally':['exclude']})
    assert 'Golden Aura: Include ally' in options()
    use(c,t,m,'Golden Aura: Include ally',ALLY)
    assert not any(n.startswith('Golden Aura:') for n in options())
    use(c,t,m,'Golden Aura: Exclude ally',ALLY)
    from tests.worker2_support import turn
    settle(t,m,t.state(m)['menu']['end_turn'])
    turn(t,m,OWNER)
    assert 'Golden Sheen: Reveal visible gold' in options()
    use(c,t,m,'Golden Sheen: Reveal visible gold')


def test_acquired_aura_keeps_activation_clock_and_recipients_between_encounters(catalog_environment,monkeypatch,tmp_path):
    from combat.ext.goruden_journey import FAMILY
    from tests.worker2_support import turn, candidate
    acquired=acquire(catalog_environment,monkeypatch)
    owner='actor:factory.gold';friend='actor:factory.friend';foe='actor:factory.foe'
    for pid,doc in [('gold',acquired),('friend',sheet([],cl=18)),('foe',sheet([],cl=18))]:
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    def cold():return CombatService(ROOT,tmp_path)
    cold().tabletop_maps.save({'display_name':'Aura return','width_squares':20,'height_squares':20,'terrain':[]})
    arena=next(k for k,v in cold().factory_arenas().items() if v['display_name']=='Aura return')
    state=cold().create_journey(project_ids=['gold','friend','foe'],arena_id=arena,
        positions={owner:{'x':3,'y':6},friend:{'x':4,'y':6},foe:{'x':15,'y':15}},
        base_paces={owner:30,friend:30,foe:30})
    jid=state['journey_id'];teams={owner:'team:gold',friend:'team:gold',foe:'team:foe'}
    state=cold().journey_start_combat(jid,state['revision'],teams,maximum_rounds=2)
    mid=state['match_id'];table=TabletopService(cold(),tmp_path)
    turn(table,mid,owner)
    settle(table,mid,candidate(cold(),mid,'Golden Aura').candidate_id)
    e=reload(tmp_path,mid)
    zone=next(z for z in e.state.zones.values() if z.active and z.owner_id==owner)
    zid=zone.zone_id
    for _ in range(12):
        if reload(tmp_path,mid).state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    e=reload(tmp_path,mid);assert e.state.terminal_result is not None
    spent=e.state.actors[owner].resources
    assert e.state.actors[friend].temporary_hp>0
    state=cold().journey_resume(jid,cold().journey_state(jid)['revision'])
    carried=state['actors'][owner]['source_states'][FAMILY]
    remaining=carried['aura_remaining_num']//carried['aura_remaining_den']
    assert 0<remaining<60
    assert cold().journey_verify(jid)['status']=='PASS'
    state=cold().journey_start_combat(jid,state['revision'],teams,maximum_rounds=1)
    mid=state['match_id'];ready(table,tmp_path,mid);e=reload(tmp_path,mid)
    assert any(z.active and z.zone_id==zid for z in e.state.zones.values())
    assert e.state.actors[owner].resources==spent
    assert any(c.data.get('rule',{}).get('save_against') for c in e.state.actors[friend].conditions.values())
    for _ in range(8):
        if reload(tmp_path,mid).state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    e=reload(tmp_path,mid)
    assert not any(ev.event_type=='TEMP_HP_GRANTED' and friend in ev.target_ids for ev in e.events)
    state=cold().journey_resume(jid,cold().journey_state(jid)['revision'])
    state=cold().journey_act(jid,state['revision'],owner,'wait',{'seconds':remaining})
    state=cold().journey_start_combat(jid,state['revision'],teams,maximum_rounds=1)
    assert not any(z.active and z.owner_id==owner for z in reload(tmp_path,state['match_id']).state.zones.values())



def test_acquired_aura_uses_committed_allies_across_team_boundaries(catalog_environment,monkeypatch,tmp_path):
    from combat.relations import relation,ALLY as ALLIED
    from combat.ext.goruden import AURA_CHOICE
    bundle=compile_character(acquire(catalog_environment,monkeypatch),actor_id=OWNER,reaction_plan={'ask':True})
    c,t,m=fixture(tmp_path,[],owner_bundle=bundle,bundle_transform=prepare,extra_foes=1,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':3,'y':7}})
    e=reload(tmp_path,m)
    c.change_relations(m,change={'kind':'ACTOR_RELATION','subject':OWNER,'other':FOE,'relation':'ALLY'},
                       expected_state_version=e.state.state_version)
    e=reload(tmp_path,m)
    assert e.state.actors[OWNER].team_id!=e.state.actors[FOE].team_id
    assert relation(e,e.state.actors[OWNER],e.state.actors[FOE])==ALLIED
    use(c,t,m,'Golden Aura')
    e=reload(tmp_path,m)
    assert any(x.condition_id==AURA_CHOICE and x.data.get('subject_id')==FOE and x.data.get('include')==1
               for x in e.state.actors[OWNER].conditions.values())
    assert any(x.data.get('rule',{}).get('save_against') for x in e.state.actors[FOE].conditions.values())
    use(c,t,m,'Golden Aura: Exclude ally',FOE)
    e=reload(tmp_path,m)
    assert not any(x.data.get('rule',{}).get('save_against') for x in e.state.actors[FOE].conditions.values())
    use(c,t,m,'Golden Aura: Include ally',FOE)
    assert any(x.data.get('rule',{}).get('save_against') for x in reload(tmp_path,m).state.actors[FOE].conditions.values())


def test_acquired_ai_executes_family_preparation_and_finishes_its_turn(catalog_environment,monkeypatch,tmp_path):
    """The real AI caller selects commands, then reaches ordinary turn completion."""
    bundle=compile_character(acquire(catalog_environment,monkeypatch),actor_id=OWNER,reaction_plan={'ask':True})
    c,t,m=fixture(tmp_path,[],owner_bundle=bundle,bundle_transform=prepare,
        modes={OWNER:'MANUAL',ALLY:'MANUAL',FOE:'LOCAL_AUTO'},
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':3,'y':7}})
    use(c,t,m,'Golden Aura')
    c.set_controller_mode(m,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    commands=[]
    for _ in range(30):
        e=reload(tmp_path,m)
        if e.state.current_actor_id!=OWNER:break
        before=e.state.event_sequence
        settle(t,m,'',auto=True)
        after=reload(tmp_path,m)
        for event in after.events:
            action=after.action_catalog.get(event.source_definition_id)
            if (event.sequence>before and event.event_type=='INTENT_ACCEPTED'
                    and event.actor_id==OWNER and action is not None
                    and action.parameters.get('goruden_ai_commands')):
                commands.append(action.display_name)
    e=reload(tmp_path,m)
    assert e.state.current_actor_id!=OWNER,'Automatic free commands must not prevent normal turn completion.'
    assert any(name.startswith('Golden Sheen:') for name in commands),commands
    assert len(commands)<=5,commands
