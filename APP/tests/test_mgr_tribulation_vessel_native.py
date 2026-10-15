"""Native acquisition, table settlement, cold reload and mechanical replay."""
import json
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import turn, settle, candidate
P='tianxia.subpath.qi.tribulation_vessel'; A='actor:factory.vessel'; B='actor:factory.enemy'; QI='resource:core.qi'; LEDGER='condition:typed.tribulation_vessel'

def game(tmp_path,monkeypatch,cl=18,acquire=True):
    docs={x:sheet(['tianxia.path.qi_cultivation.feature.qi_sensing'],cl=cl,name=n,key='WIS',kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.bi_shou','name':'Bi Shou (Dagger)','quantity':1}]}}) for x,n in [('vessel','Wren'),('enemy','Mara')]}
    for d in docs.values():d.setdefault('path_and_subpath',{}).update(path_record_id='tianxia.path.qi_cultivation',path_record_ids=['tianxia.path.qi_cultivation'],paths=[{'path_id':'tianxia.path.qi_cultivation','attainment':cl}])
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',lambda self,pid:docs[pid])
    arena={'display_name':'Storm courtyard','stable_id':'battlefield:vessel-test','width_squares':12,'height_squares':12,'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self,**kw:{'scene':arena})
    def cold():return CombatService(ROOT,tmp_path)
    state=cold().create_journey(project_ids=list(docs),arena_id='scene',positions={A:{'x':3,'y':3},B:{'x':4,'y':3}},base_paces={A:100,B:100});jid=state['journey_id']
    def world(kind,scope,value,readers=None):
        before=cold().journey_state(jid)
        after=cold().journey_world_fact(jid,before['revision'],{'source':P,'subject':A,'kind':kind,'scope':scope,'value':value,'expires_at':100000,'readers':readers or [A]})
        assert cold().journey_state(jid)==after
        return after
    if acquire:
        state=world('source_access','scripture',{'route':'restricted_scripture','source_rule':'The table owner grants access to a surviving Tribulation Vessel scripture.'})
        state=cold().journey_acquire_source(jid,state['revision'],A,P,{'access_scope':'scripture'})
        assert not any(P in m for m in docs['vessel']['path_and_subpath']['path_feature_record_ids'])
    return cold,jid,world

def fight(cold,jid,tmp_path):
    state=cold().journey_state(jid);mid=cold().journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'})['match_id']
    service=cold();table=TabletopService(service,tmp_path);turn(table,mid,A)
    return service,table,mid

def loaded(cold,mid):
    s=cold()._load_session(mid);assert s.mechanical.replay()['status']=='PASS';return s.engine

def ledger(engine):
    rows=[c for c in engine.state.actors[A].conditions.values() if c.condition_id==LEDGER]
    return json.loads(rows[0].data['ledger']) if rows else {'charges':[],'history':[]}

def test_restricted_scripture_acquisition_cold_progression(tmp_path,monkeypatch):
    cold,jid,_=game(tmp_path,monkeypatch)
    bundle=cold().journey_state(jid)['actors'][A]['bundle']
    assert any(a['display_name']=='Walking Tribulation' for a in bundle['action_catalog'])
    service,table,mid=fight(cold,jid,tmp_path)
    assert loaded(cold,mid).state.actors[A].resources[QI]==30

def test_wrong_owner_default_inert(tmp_path,monkeypatch):
    cold,jid,_=game(tmp_path,monkeypatch,acquire=False)
    service,table,mid=fight(cold,jid,tmp_path)
    assert not any('Tribulation' in a.display_name for a in loaded(cold,mid).action_catalog.values())
    assert ledger(loaded(cold,mid))['charges']==[]
