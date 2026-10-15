"""Real acquisition -> journey/committed combat intent -> cold replay."""
from copy import deepcopy
import pytest
from combat.gate5_service import CombatService,FACTORY_ACTOR_PREFIX
from combat.gate2_runtime_models import ActionIntent
PARENT='tianxia.subpath.body.sumo'
PREFIX=PARENT+'.feature.'
ROOTED='condition:typed.stance.rooted_stance'
DECLINED='condition:typed.sumo_rooting_declined'
LEVELS=dict(zip(('rooted_stance','sumo_strike','ring_breaker','yokozuna_presence','immovable_god'),(3,6,10,14,18)))
from tests.test_riders_c7 import sheet,answers,STAMINA
from tests.h1_support import ROOT
A=FACTORY_ACTOR_PREFIX+'sumo'
B=FACTORY_ACTOR_PREFIX+'other'


def game(tmp_path,monkeypatch,cl=18,other_cl=18,objects=(),skills=()):
    sheets={'sumo':sheet([],cl=cl,name='Sumo practitioner',mods={'CON':4,'CHA':-1}),
            'other':sheet([],cl=other_cl,name='Other practitioner')}
    sheets['sumo']['ability_scores_and_statistics']['skills']=list(skills)
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',lambda self,pid:deepcopy(sheets[pid]))
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self:{'scene':{
        'stable_id':'scene:sumo','width_squares':20,'height_squares':14,'square_size_ft':5,
        'terrain_regions':[],'objects':list(objects),'starting_positions':{}}})
    def cold():return CombatService(ROOT,tmp_path)
    state=cold().create_journey(project_ids=['sumo','other'],arena_id='scene',
        positions={A:{'x':3,'y':6},B:{'x':4,'y':6}},base_paces={A:5,B:5},control_modes={A:'MANUAL',B:'MANUAL'})
    return cold,state['journey_id']


def acquire(cold,jid,aid=A):
    service=cold();state=service.journey_state(jid)
    state=service.journey_world_fact(jid,state['revision'],{'source':PARENT,'subject':aid,'kind':'school_access','scope':'school',
        'value':{'school':PARENT,'teacher':'Native Open School instruction','source_rule':'Body Path R8: one Subpath at CL3; Sumo Open School'},
        'expires_at':1000,'readers':[]})
    state=service.journey_acquire_source(jid,state['revision'],aid,PARENT,{'access_scope':'school'})
    assert cold().journey_state(jid)==state
    return state


def encounter(cold,jid):
    state=cold().journey_state(jid)
    out=cold().journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'},positions={A:{'x':3,'y':6},B:{'x':4,'y':6}},maximum_rounds=4)
    return out['match_id']


def act(cold,mid,name,*,target=None,picks=None):
    session=cold()._load_session(mid);e=session.engine
    options=[c for c in e.legal_candidates() if c.display_name.startswith(name) and (target is None or target in c.target_ids)]
    assert options,(name,e.state.current_actor_id,[c.display_name for c in e.legal_candidates()])
    c=options[0];answers(e,picks or {})
    session.submit_intent(ActionIntent(intent_id='sumo-'+str(e.state.event_sequence),decision_id=c.decision_id,candidate_id=c.candidate_id,
        state_version=c.state_version,actor_id=c.actor_id,target_ids=c.target_ids,destination=c.destination),reaction_provider=e._gate4_reaction_provider)
    loaded=cold()._load_session(mid)
    assert loaded.engine.state.model_dump(mode='json')==e.state.model_dump(mode='json')
    assert not loaded.verify()['controller_open_transactions']
    return loaded.engine


def owner_turn(cold,mid,aid=A):
    for _ in range(6):
        e=cold()._load_session(mid).engine
        if e.state.current_actor_id==aid:return e
        act(cold,mid,'End Turn')
    raise AssertionError('No owner turn')


@pytest.mark.parametrize('cl,count',[(2,0),(3,1),(6,2),(10,3),(14,4),(18,5)])
def test_native_acquisition_progression_and_wrong_owner(tmp_path,monkeypatch,cl,count):
    cold,jid=game(tmp_path,monkeypatch,cl)
    if cl<3:
        with pytest.raises(ValueError,match='attainment 3'):acquire(cold,jid)
        return
    state=acquire(cold,jid)
    assert state['events'][-1]['features']==[PREFIX+s for s in list(LEVELS)[:count]]
    assert not cold().journey_menu(jid,B)['properties']
    with pytest.raises(ValueError,match='must own'):cold().journey_act(jid,state['revision'],B,'sumo_stance',{'operation':'enter'})
    with pytest.raises(ValueError,match='already acquired'):acquire(cold,jid)


def test_school_access_is_native_and_required(tmp_path,monkeypatch):
    cold,jid=game(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='Record actual'):cold().journey_acquire_source(jid,0,A,PARENT,{'access_scope':'forged'})
    before=cold().journey_state(jid)
    with pytest.raises(ValueError,match='table-owner'):cold().journey_act(jid,0,A,'declare_fact',{'source':PARENT,'subject':A,'kind':'school_access','scope':'school',
        'value':{'school':PARENT,'teacher':'Invented','source_rule':'name'},'expires_at':1000,'readers':[]})
    assert cold().journey_state(jid)==before


def test_rooted_native_distance_expiry_and_replay(tmp_path,monkeypatch):
    cold,jid=game(tmp_path,monkeypatch,cl=14);acquire(cold,jid);mid=encounter(cold,jid);owner_turn(cold,mid)
    e=act(cold,mid,'Rooted Stance');me=e.state.actors[A]
    assert any(c.condition_id==ROOTED and c.expires_on=='UNTIL_REMOVED' for c in me.conditions.values())
    assert not any(c.condition_id==ROOTED for c in e.state.actors[B].conditions.values())
    e=act(cold,mid,'Move to 3,9');assert any(c.condition_id==ROOTED for c in e.state.actors[A].conditions.values())
    e=act(cold,mid,'Move to 3,10');assert not any(c.condition_id==ROOTED for c in e.state.actors[A].conditions.values())


def test_yokozuna_native_travel_and_combat_intimidation(tmp_path,monkeypatch):
    cold,jid=game(tmp_path,monkeypatch,cl=14,skills=[{'skill':'Intimidation','bonus':9,'proficiency_multiplier':2}]);state=acquire(cold,jid)
    state=cold().journey_act(jid,state['revision'],A,'sumo_stance',{'operation':'enter'})
    menu=cold().journey_menu(jid,A)
    assert {o['payload']['ability'] for o in menu['options'] if o['kind']=='sumo_intimidate'}=={'CON','CHA'}
    assert menu['properties']['sumo_carrying_capacity_lb']>0
    for ability,expected in [('CON',16),('CHA',11)]:
        state=cold().journey_act(jid,state['revision'],A,'sumo_intimidate',{'ability':ability})
        assert state['events'][-1]['roll']['modifier']==expected
        assert cold().journey_state(jid)==state
    mid=encounter(cold,jid);owner_turn(cold,mid)
    e=act(cold,mid,'Yokozuna Presence: Constitution')
    assert any(r.reason.endswith(':Intimidation') and r.modifier==16 for r in e.rolls)


def test_immovable_auto_root_decline_resume_persist(tmp_path,monkeypatch):
    cold,jid=game(tmp_path,monkeypatch);acquire(cold,jid);mid=encounter(cold,jid);e=owner_turn(cold,mid)
    assert any(c.condition_id==ROOTED for c in e.state.actors[A].conditions.values())
    e=act(cold,mid,'End Rooted Stance');assert any(c.condition_id==DECLINED for c in e.state.actors[A].conditions.values())
    e=act(cold,mid,'Move to 3,10');assert not any(c.condition_id==ROOTED for c in e.state.actors[A].conditions.values())
    e=act(cold,mid,'Resume automatic Rooted Stance');assert any(c.condition_id==ROOTED for c in e.state.actors[A].conditions.values())


def test_sumo_strike_native_hit_cost_collision_replay(tmp_path,monkeypatch):
    cold,jid=game(tmp_path,monkeypatch,objects=[{'id':1,'kind':'door','x':6,'y':6,'hp':999}]);acquire(cold,jid);mid=encounter(cold,jid);e=owner_turn(cold,mid)
    attack=next(a.display_name for a in e.action_catalog.values() if a.owner_id==A and a.economy.value=='ACTION' and any(
        r.get('type')=='attack' and r.get('attack_kind')=='unarmed' for r in (a.parameters.get('typed') or {}).get('effects',[])))
    e=act(cold,mid,attack,target=B,picks={'sumo_strike':['Push it']})
    assert e.state.actors[A].resources[STAMINA]==59
    assert e.state.actors[B].position.x==5
    assert any(ev.event_type=='OBJECT_UPDATED' for ev in e.events)


def test_ring_breaker_native_cost_distance_prone_step_replay(tmp_path,monkeypatch):
    cold,jid=game(tmp_path,monkeypatch,cl=10);acquire(cold,jid);mid=encounter(cold,jid);owner_turn(cold,mid)
    e=act(cold,mid,'Ring Breaker',target=B,picks={'ring_breaker_distance':['15'],'ring_breaker_step':['enter']})
    assert e.state.actors[A].resources[STAMINA]==57
    assert e.state.actors[B].position.x==7
    assert e.state.actors[A].position.x==4
    assert any(c.condition_id.endswith('prone') for c in e.state.actors[B].conditions.values())
