"""Installed Qi character -> source acquisition -> journey/table -> replay."""
import json
import zipfile
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import turn, candidate, settle
FAMILY='tianxia.subpath.qi.living_quicksilver_immortal_embryo'
FEATURES=[FAMILY+'.feature.'+s for s in ('living_mercury_body','divide_the_immortal_embryo','assimilate_the_pattern','thousandfold_quicksilver_court','undying_prima_materia')]
A='actor:factory.mercury';B='actor:factory.opponent';QI='resource:core.qi';MASS='resource:named.quicksilver_mass'

def setup(tmp_path,monkeypatch,cl=18,acquire=True):
    for name in ('mercury','opponent'):
        doc=sheet(['tianxia.path.qi_cultivation.feature.qi_sensing'],cl=cl,name=name.title())
        doc['path_and_subpath'].update(path_record_id='tianxia.path.qi_cultivation',path_record_ids=['tianxia.path.qi_cultivation'],paths=[{'path_id':'tianxia.path.qi_cultivation','attainment':cl}])
        folder=tmp_path/'portable_characters'/name;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    arena={'display_name':'Mercury courtyard','stable_id':'battlefield:mercury','width_squares':12,'height_squares':12,'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self,**kw:{'scene':arena})
    def cold():return CombatService(ROOT,tmp_path)
    state=cold().create_journey(project_ids=['mercury','opponent'],arena_id='scene',positions={A:{'x':3,'y':3},B:{'x':8,'y':3}},base_paces={A:100,B:100})
    jid=state['journey_id']
    def world(kind,scope,value,subject=A,readers=None):
        s=cold();state=s.journey_state(jid)
        return s.journey_world_fact(jid,state['revision'],{'source':FAMILY,'subject':subject,'kind':kind,'scope':scope,'value':value,'expires_at':int(state['seconds'])+2592000,'readers':readers or [A]})
    def act(kind,payload=None,who=A):
        s=cold();state=s.journey_state(jid);after=s.journey_act(jid,state['revision'],who,kind,payload or {})
        assert cold().journey_state(jid)==after
        return after
    if acquire:
        world('source_access','inheritance',{'variant':FAMILY,'route':'direct','source_rule':'A living mercury inheritance grants the first Qi Subpath choice.'})
        state=cold().journey_state(jid);state=cold().journey_acquire_source(jid,state['revision'],A,FAMILY,{'access_scope':'inheritance'})
        assert any(e['kind']=='QUICKSILVER_SOURCE_ACQUIRED' for e in state['events'])
    return cold,jid,act,world

def combat(cold,jid,tmp_path):
    s=cold();state=s.journey_state(jid);mid=s.journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'})['match_id']
    table=TabletopService(cold(),tmp_path);turn(table,mid,A)
    return table,mid

def engine(cold,mid):
    session=cold()._load_session(mid)
    assert session.mechanical.replay()['status']=='PASS'
    assert not any(e.event_type=='GM_RIDER' and e.source_definition_id.startswith('ext:combat.ext.mgr_reserve_living') for e in session.engine.events)
    return session.engine

def use(cold,table,mid,label,picks=None):
    c=candidate(cold(),mid,label)
    settle(table,mid,c.candidate_id,picks=picks)
    return engine(cold,mid)

@pytest.mark.parametrize('cl,count',[(3,1),(6,2),(10,3),(14,4),(18,5)])
def test_native_access_acquires_only_earned_progression_and_scene_mass(tmp_path,monkeypatch,cl,count):
    cold,jid,act,world=setup(tmp_path,monkeypatch,cl)
    state=cold().journey_state(jid);bundle=state['actors'][A]['bundle']
    owned={p['feature_id'] for p in bundle['typed_passives'] if p.get('block')=='living_quicksilver'}
    assert owned==set(FEATURES[:count])
    assert state['actors'][A]['resources'][MASS]==2
    assert MASS not in state['actors'][B]['resources']
    table,mid=combat(cold,jid,tmp_path);e=engine(cold,mid)
    assert e.state.actors[A].resources[MASS]==2
    assert MASS not in e.state.actors[B].resources

def test_no_access_or_unknown_source_cannot_grant_features(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,acquire=False)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):cold().journey_acquire_source(jid,before['revision'],A,FAMILY,{'access_scope':'invented'})
    assert cold().journey_state(jid)==before
    with pytest.raises(ValueError):cold().journey_acquire_source(jid,before['revision'],A,'unknown',{})
    assert cold().journey_state(jid)==before

def test_body_creation_rejoin_cost_capacity_and_cold_replay(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,6)
    table,mid=combat(cold,jid,tmp_path)
    e=use(cold,table,mid,'Create Quicksilver Body: 2 Qi')
    bodies=[o for o in e.state.objects.values() if o.component.get('quicksilver_body') and not o.destroyed]
    assert len(bodies)==1 and bodies[0].maximum_hp==12 and bodies[0].ac==14
    assert e.state.actors[A].resources[QI]==28
    e=use(cold,table,mid,'Rejoin: regain Quicksilver Mass')
    assert all(o.destroyed for o in e.state.objects.values() if o.component.get('quicksilver_body'))
    assert e.state.actors[A].resources[MASS]==3
