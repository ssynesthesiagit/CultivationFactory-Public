"""Native Forbidden access/acquisition, actual resource events, table commit and cold replay."""
import json
import zipfile
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import settle, candidate
P='tianxia.subpath.body.ten_thousand_parasite_vessel';F=P+'.feature.'
A='actor:factory.parasite';B='actor:factory.opponent';BROOD='resource:named.brood';INFESTED='condition:typed.infested'

def game(tmp_path,cl=18,*,acquire=True,hostile=True,dc=100):
    for aid in (A,B):
        doc=sheet([],cl=cl,primary='Stamina',dc=dc if aid==A else 16,name='Wren' if aid==A else 'Mara')
        doc['identity']['path']='Body Refining'
        doc['ability_scores_and_statistics']['hit_points']['maximum']=500
        doc['path_and_subpath']={'path_record_id':'tianxia.path.body_refining','path_record_ids':['tianxia.path.body_refining'],
            'paths':[{'path_id':'tianxia.path.body_refining','attainment':cl}]}
        folder=tmp_path/'portable_characters'/aid.removeprefix('actor:factory.');folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    s=CombatService(ROOT,tmp_path)
    state=s.create_journey(project_ids=['parasite','opponent'],arena_id='battlefield:map.builtin-sect-trial-platform',
        positions={A:{'x':3,'y':6},B:{'x':4,'y':6}},base_paces={A:100,B:100});jid=state['journey_id']
    if acquire:
        state=s.journey_world_fact(jid,state['revision'],{'source':P,'subject':A,'kind':'source_access','scope':'access',
            'value':{'subpath':P,'source_rule':'Table-owner Forbidden Method access under Body Refining Compendium R8, section 42'},
            'expires_at':20000,'readers':[A]})
        state=s.journey_acquire_source(jid,state['revision'],A,P,{'access_scope':'access'})
        if hostile:
            state=s.journey_world_fact(jid,state['revision'],{'source':P,'subject':A,'kind':'hostility','scope':'mara',
                'value':{'attacker':B,'genuine':1,'willing_ally':0,'controlled':0,'farming':0},'expires_at':20000,'readers':[A]})
            state=s.journey_act(jid,state['revision'],A,'parasite_record_hostility',{'scope':'mara'})
    return s,jid,state

def cold(tmp_path,mid):
    saved=CombatService(ROOT,tmp_path)._load_session(mid)
    assert saved.mechanical.replay()['status']=='PASS'
    return saved.engine

def turn(table,mid,aid):
    for _ in range(20):
        state=table.state(mid)
        if state['menu']['actor_id']==aid:return
        settle(table,mid,state['menu']['end_turn'],{'choice:needle.internal_brood':None})
    raise AssertionError('No native turn')

def fight(tmp_path,**kw):
    s,jid,state=game(tmp_path,**kw)
    mid=s.journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'})['match_id']
    s=CombatService(ROOT,tmp_path);table=TabletopService(s,tmp_path);turn(table,mid,A)
    return s,table,mid

def strike(s,table,mid,attacker,target,picks=None):
    e=s._load_session(mid).engine
    a=next(a for a in e.action_catalog.values() if a.owner_id==attacker and
        a.economy.value=='ACTION' and any(r.get('type')=='attack' and r.get('attack_kind')=='unarmed' for r in ((a.parameters or {}).get('typed') or {}).get('effects',[])))
    return settle(table,mid,candidate(s,mid,a.display_name,target=target).candidate_id,picks or {})

def next_round(table,mid,aid=A,picks=None):
    settle(table,mid,table.state(mid)['menu']['end_turn'],picks or {'choice:needle.internal_brood':None})
    turn(table,mid,aid)

@pytest.mark.parametrize('cl,count',[(3,1),(6,2),(10,3),(14,4),(18,5)])
def test_native_source_acquisition_and_cold_progression(tmp_path,cl,count):
    s,jid,state=game(tmp_path,cl);features=state['actors'][A]['source_states'][P]['features']
    assert len(features)==count
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state
    with pytest.raises(ValueError,match='already acquired'):
        s.journey_acquire_source(jid,state['revision'],A,P,{'access_scope':'access'})
    assert s.journey_state(jid)==state
    mid=s.journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'})['match_id']
    assert cold(tmp_path,mid).state.actors[A].resources[BROOD]==0

@pytest.mark.parametrize('hostile',[True,False])
def test_normal_brood_requires_real_damage_and_admitted_hostility(tmp_path,hostile):
    s,table,mid=fight(tmp_path,cl=3,hostile=hostile);turn(table,mid,B)
    before=cold(tmp_path,mid)
    for _ in range(6):
        strike(s,table,mid,B,A);e=cold(tmp_path,mid)
        if e.state.actors[A].current_hp<before.state.actors[A].current_hp:break
        next_round(table,mid,B)
    assert e.state.actors[A].current_hp<before.state.actors[A].current_hp
    assert e.state.actors[A].resources[BROOD]==int(hostile)

def test_native_infestation_records_source_cl_and_trigger_status(tmp_path):
    s,table,mid=fight(tmp_path)
    settle(table,mid,candidate(s,mid,'Ten-Thousand Worm Demon Body').candidate_id);next_round(table,mid,A)
    for _ in range(6):
        strike(s,table,mid,A,B,{'choice:needle.path_hit.'+F+'internal_brood':'first','choice:needle.parasite_damage_type':'NECROTIC'})
        e=cold(tmp_path,mid);records=[c for c in e.state.actors[B].conditions.values() if c.condition_id==INFESTED]
        if records:break
        next_round(table,mid,A)
    assert records
    assert records[0].data['source_cl']==18
    assert records[0].data['trigger_status']=='waiting'
    turn(table,mid,B)
    settle(table,mid,candidate(s,mid,'Dash').candidate_id,{'choice:needle.parasite_sovereignty':'brood'})
    final=cold(tmp_path,mid)
    assert not any(c.condition_id==INFESTED for c in final.state.actors[B].conditions.values())
    assert any(e.event_type=='DAMAGE_COMMITTED' and e.source_definition_id==F+'gnawing_infestation' for e in final.events)


def test_unowned_source_is_default_inert_and_access_cannot_be_self_declared(tmp_path):
    s,jid,state=game(tmp_path,acquire=False)
    with pytest.raises(ValueError):
        s.journey_act(jid,state['revision'],A,'declare_fact',{'source':P,'subject':A,'kind':'source_access','scope':'fake',
            'value':{'subpath':P,'source_rule':'self assertion'},'expires_at':100,'readers':[A]})
    assert s.journey_state(jid)==state
    mid=s.journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'})['match_id']
    e=cold(tmp_path,mid)
    assert BROOD not in e.state.actors[A].resources
    assert not any(a.display_name in ('Brood Tide','Ten-Thousand Worm Demon Body') for a in e.action_catalog.values())


def test_source_progression_uses_owning_path_attainment_not_overall_cl(tmp_path):
    s,jid,state=game(tmp_path,cl=3,acquire=False)
    # Actual installed build changes overall attainment, preserving Body CL3.
    folder=tmp_path/'portable_characters'/'parasite'/'current.zip'
    with zipfile.ZipFile(folder) as z:doc=json.loads(z.read('Tianxia_Owner_Character_Sheet_v1.json'))
    doc['identity']['cultivation_level']=18
    with zipfile.ZipFile(folder,'w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    state=s.journey_world_fact(jid,state['revision'],{'source':P,'subject':A,'kind':'source_access','scope':'access',
        'value':{'subpath':P,'source_rule':'Table-owner Forbidden Method access'},'expires_at':20000,'readers':[A]})
    state=s.journey_acquire_source(jid,state['revision'],A,P,{'access_scope':'access'})
    assert state['actors'][A]['source_states'][P]['features']==[F+'internal_brood']
    own=state['actors'][A]['bundle']
    assert own['parasite_vessel_native_effective_cl']==3
    assert all(r.get('cl')==3 for r in own['typed_passives'] if r.get('kind')=='parasite')


def test_zero_resource_and_scene_boundary_are_not_reset_by_reopen(tmp_path):
    s,jid,state=game(tmp_path)
    before=state['actors'][A]['resources'][BROOD]
    state=CombatService(ROOT,tmp_path).journey_end_scene(jid,state['revision'],'The pursuit and its consequences have ended.')
    assert before==state['actors'][A]['resources'][BROOD]==0
    assert state['actors'][A]['source_states'][P]['features']
    assert 'hostility' not in state['actors'][A]['source_states'][P]
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state
