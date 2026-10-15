"""Real source acquisition, native table actions, cold state and mechanical replay."""
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import candidate, settle, turn
P='tianxia.subpath.qi.demon_prison_seal_cultivator'
A='actor:factory.warden'; B='actor:factory.visitor'; QI='resource:core.qi'
STATE='condition:typed.demon_prison_state'

def game(tmp_path,monkeypatch,cl=18,nature='frost',owner=True,dc=100):
    docs={'warden':sheet(['tianxia.path.qi_cultivation.feature.qi_sensing','tianxia.path.qi_cultivation.feature.domain_armament'],cl=cl,key='CHA',dc=dc),
          'visitor':sheet([],cl=cl,key='CHA')}
    docs['warden']['ability_scores_and_statistics']['technique_attack_bonus']=100
    import hashlib
    monkeypatch.setattr('combat.journey.secrets.token_hex',lambda n:hashlib.sha256((tmp_path.name+nature+str(cl)).encode()).hexdigest()[:2*n])
    for d in docs.values():
        d.setdefault('path_and_subpath',{}).update(path_record_id='tianxia.path.qi_cultivation',path_record_ids=['tianxia.path.qi_cultivation'],
            paths=[{'path_id':'tianxia.path.qi_cultivation','attainment':d['identity']['cultivation_level']}])
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',lambda self,pid:docs[pid])
    arena={'display_name':'Seal courtyard','stable_id':'battlefield:demon-prison','width_squares':16,'height_squares':16,'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self,**kw:{'scene':arena})
    def cold():return CombatService(ROOT,tmp_path)
    st=cold().create_journey(project_ids=list(docs),arena_id='scene',positions={A:{'x':3,'y':3},B:{'x':5,'y':3}},base_paces={A:100,B:100})
    jid=st['journey_id']
    if owner:
        st=cold().journey_world_fact(jid,st['revision'],{'source':P,'subject':A,'kind':'source_access','scope':'access',
            'value':{'source_rule':'A bound demon prison inheritance granted by the table owner','source_kind':'inherited_prison'},'expires_at':2592000,'readers':[A]})
        st=cold().journey_acquire_source(jid,st['revision'],A,P,{'access_scope':'access','nature':nature})
        assert not any(P in x for x in docs['warden']['path_and_subpath']['path_feature_record_ids'])
    def act(kind,payload=None,actor=A):
        s=cold().journey_state(jid); out=cold().journey_act(jid,s['revision'],actor,kind,payload or {})
        assert cold().journey_state(jid)==out
        return out
    return cold,jid,act

def fight(tmp_path,cold,jid):
    st=cold().journey_state(jid)
    mid=cold().journey_start_combat(jid,st['revision'],{A:'team:a',B:'team:b'})['match_id']
    s=cold();t=TabletopService(s,tmp_path);turn(t,mid,A)
    return s,t,mid

def state(cold,mid):
    session=cold()._load_session(mid)
    assert session.mechanical.replay()['status']=='PASS'
    return session.engine

def prison(e):
    return next(c.data for c in e.state.actors[A].conditions.values() if c.condition_id==STATE)

def test_native_acquisition_and_chain_payment_reload(tmp_path,monkeypatch):
    cold,jid,act=game(tmp_path,monkeypatch,cl=3)
    st=cold().journey_state(jid);before=st['actors'][A]['resources'][QI]
    st=act('demon_prison_open')
    assert st['actors'][A]['resources'][QI]==before-1
    s,t,mid=fight(tmp_path,cold,jid);e=state(cold,mid)
    assert prison(e)['chains']==1 and prison(e)['nature']=='frost'
    assert not any(c.display_name.startswith('Demon Projection') for c in e.legal_candidates())

@pytest.mark.parametrize('nature',['ash','frost','storm','shadow','venom','stone'])
def test_projection_native_all_natures(tmp_path,monkeypatch,nature):
    cold,jid,act=game(tmp_path,monkeypatch,nature=nature)
    act('demon_prison_open');act('demon_prison_open')
    s,t,mid=fight(tmp_path,cold,jid)
    c=candidate(s,mid,'Demon Projection: '+{'ash':'Fire','frost':'Cold','storm':'Lightning','shadow':'Necrotic','venom':'Poison','stone':'Bludgeoning'}[nature],target=B)
    settle(t,mid,c.candidate_id)
    e=state(cold,mid)
    assert e.state.actors[A].resources[QI]==cold().journey_state(jid)['actors'][A]['resources'][QI]-1
    assert e.state.actors[B].current_hp<e.state.actors[B].maximum_hp


def test_king_and_prison_native_anchor_reload(tmp_path,monkeypatch):
    cold,jid,act=game(tmp_path,monkeypatch)
    s,t,mid=fight(tmp_path,cold,jid)
    before=state(cold,mid).state.actors[A].resources[QI]
    settle(t,mid,candidate(s,mid,'Demon King Behind the Seal').candidate_id)
    e=state(cold,mid);assert prison(e)['chains']==3 and prison(e)['king_until']>0
    settle(t,mid,candidate(s,mid,'Turn the Prison Outward',target=B).candidate_id)
    e=state(cold,mid)
    assert e.state.actors[A].resources[QI]==before-11
    holds=[c for c in e.state.actors[B].conditions.values() if c.data.get('demon_prison_anchor')]
    assert len(holds)==1
    obj=e.state.objects[holds[0].data['demon_prison_anchor']]
    assert obj.maximum_hp==72 and obj.ac==100 and obj.owner_id==A
    assert holds[0].data['king_prison']==1
    assert not any(c.display_name=='Demon King Behind the Seal' for c in e.legal_candidates())
    assert any(c.display_name.startswith('Demon Projection (free)') for c in e.legal_candidates())

@pytest.mark.parametrize('owner',[False,True])
def test_default_inert_wrong_owner_and_scene_closure(tmp_path,monkeypatch,owner):
    cold,jid,act=game(tmp_path,monkeypatch,owner=owner)
    if not owner:
        with pytest.raises(ValueError):act('demon_prison_open')
    else:
        act('demon_prison_open')
        st=cold().journey_state(jid)
        cold().journey_end_scene(jid,st['revision'],'The meaningful encounter ends')
    s,t,mid=fight(tmp_path,cold,jid);e=state(cold,mid)
    if owner:assert prison(e)['chains']==0
    else:assert not any(c.condition_id==STATE for c in e.state.actors[A].conditions.values())
    assert not any(c.condition_id==STATE for c in e.state.actors[B].conditions.values())


@pytest.mark.parametrize('cl,maximum',[(3,1),(6,2),(10,3)])
def test_chain_unlocks_follow_native_qi_attainment(tmp_path,monkeypatch,cl,maximum):
    cold,jid,act=game(tmp_path,monkeypatch,cl=cl)
    before=cold().journey_state(jid)['actors'][A]['resources'][QI]
    for _ in range(maximum):act('demon_prison_open')
    saved=cold().journey_state(jid)
    with pytest.raises(ValueError):act('demon_prison_open')
    assert cold().journey_state(jid)==saved
    s,t,mid=fight(tmp_path,cold,jid);e=state(cold,mid)
    assert prison(e)['chains']==maximum
    assert prison(e)['corruption']==int(maximum==3)
    assert e.state.actors[A].resources[QI]==before-maximum


def test_native_corruption_and_broken_chain_consequences(tmp_path,monkeypatch):
    cold,jid,act=game(tmp_path,monkeypatch,cl=10)
    for _ in range(3):act('demon_prison_open')
    for _ in range(9):act('demon_prison_close',{'chains':2});act('demon_prison_open')
    act('demon_prison_close',{'chains':2})
    saved=cold().journey_state(jid)
    with pytest.raises(ValueError):act('demon_prison_open')
    assert cold().journey_state(jid)==saved
    st=act('demon_prison_open',{'accept_broken':1})
    assert st['actors'][A]['encounter_snapshot']['current_hp']<60
    with pytest.raises(ValueError):act('demon_prison_close',{'chains':1})
    s,t,mid=fight(tmp_path,cold,jid);e=state(cold,mid)
    assert prison(e)['broken']==1 and prison(e)['chains']==3
    assert e.state.actors[A].resources['resource:named.corruption']==10


def test_source_access_expiry_privacy_and_permanent_nature(tmp_path,monkeypatch):
    cold,jid,act=game(tmp_path,monkeypatch)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):cold().journey_acquire_source(jid,before['revision'],A,P,{'access_scope':'access','nature':'ash'})
    assert cold().journey_state(jid)==before
    with pytest.raises(ValueError):act('demon_prison_open',actor=B)
    with pytest.raises(ValueError):act('declare_fact',{'source':P,'subject':A,'kind':'procedure','scope':'false','value':{'kind':'purify'},'expires_at':100,'readers':[A]})


def test_king_flight_and_armament_control_query_are_native_and_inert(tmp_path,monkeypatch):
    from combat.flight import profile
    from combat.ext.qi_path import armament_control_range
    cold,jid,act=game(tmp_path,monkeypatch)
    s,t,mid=fight(tmp_path,cold,jid)
    e=state(cold,mid);before=armament_control_range(e,e.state.actors[A])
    assert profile(e,e.state.actors[A]).speed_ft==0
    settle(t,mid,candidate(s,mid,'Demon King Behind the Seal').candidate_id)
    e=state(cold,mid)
    assert profile(e,e.state.actors[A]).speed_ft==40 and profile(e,e.state.actors[A]).hover
    assert armament_control_range(e,e.state.actors[A])==before+30
    assert profile(e,e.state.actors[B]).speed_ft==0


def test_initial_prison_success_has_no_anchor_and_expires_at_target_start(tmp_path,monkeypatch):
    cold,jid,act=game(tmp_path,monkeypatch,dc=-100)
    s,t,mid=fight(tmp_path,cold,jid)
    settle(t,mid,candidate(s,mid,'Turn the Prison Outward',target=B).candidate_id)
    e=state(cold,mid)
    assert not any(o.component.get('demon_prison') for o in e.state.objects.values())
    assert any(c.condition_id=='condition:typed.demon_prison_slow' for c in e.state.actors[B].conditions.values())
    turn(t,mid,B);e=state(cold,mid)
    assert not any(c.condition_id=='condition:typed.demon_prison_slow' for c in e.state.actors[B].conditions.values())
