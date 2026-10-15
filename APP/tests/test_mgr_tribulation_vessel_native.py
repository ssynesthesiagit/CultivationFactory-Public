"""Native acquisition, table settlement, cold reload and mechanical replay."""
import json
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import turn, settle, candidate
P='tianxia.subpath.qi.tribulation_vessel'; A='actor:factory.vessel'; B='actor:factory.enemy'; QI='resource:core.qi'; LEDGER='condition:typed.tribulation_vessel'

def game(tmp_path,monkeypatch,cl=18,acquire=True,profiles=()):
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
        for index,profile in enumerate(profiles):world('calamity_profile','hazard-'+str(index),profile)
        state=world('source_access','scripture',{'route':'restricted_scripture','source_rule':'The table owner grants access to a surviving Tribulation Vessel scripture.'})
        state=cold().journey_acquire_source(jid,state['revision'],A,P,{'access_scope':'scripture','hazard_scopes':['hazard-'+str(i) for i in range(len(profiles))]})
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

def hazard(kind='Flame',cl=21):
    from combat.ext.mgr_reserve_tribulation_vessel_gather_calamity import DAMAGE
    return {'name':kind+' vent','source_rule':'An exposed natural vent imposes this genuine save and damage; it cannot refund its damage or normal Qi cost.','type':kind,'source_cl':cl,'damage_type':DAMAGE[kind][0],'dice':{'count':1,'sides':4},'dc':30,'save':'con','status':'growing','category':'environmental catastrophe','position':{'x':3,'y':3},'legendary':0,'formal_tribulation':0,'cost_qi':1}

def face(service,table,mid,name='Flame',picks=None):
    return settle(table,mid,candidate(service,mid,'Face Calamity: '+name+' vent').candidate_id,picks=picks or {'choice:vessel.consume_damage':None})

@pytest.mark.parametrize('cl,cap',[(3,4),(6,4),(10,4),(14,7),(18,7)])
def test_real_hazard_cost_damage_typed_great_collection_round_and_replay(tmp_path,monkeypatch,cl,cap):
    cold,jid,_=game(tmp_path,monkeypatch,cl=cl,profiles=[hazard(cl=cl+3)])
    service,table,mid=fight(cold,jid,tmp_path)
    face(service,table,mid)
    engine=loaded(cold,mid);d=ledger(engine)
    assert len(d['charges'])==2 and all(c['type']=='Flame' and c['source_cl']==cl+3 for c in d['charges'])
    assert engine.state.actors[A].current_hp<60 and engine.state.actors[A].resources[QI]==29
    assert d['history']==['Flame'] and len(set(c['event'] for c in d['charges']))==1
    assert ('Walking Tribulation' in {a.display_name for a in engine.action_catalog.values()})==(cl>=18)


def test_release_real_charges_select_save_damage_rider_cost_reload(tmp_path,monkeypatch):
    cold,jid,_=game(tmp_path,monkeypatch,cl=10,profiles=[hazard(cl=13)])
    service,table,mid=fight(cold,jid,tmp_path);face(service,table,mid)
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,A)
    settle(table,mid,candidate(service,mid,'Tribulation Release').candidate_id,picks={'choice:vessel.spend':None,'choice:vessel.release_targets':[B],'choice:vessel.release_save':'con'})
    engine=loaded(cold,mid)
    assert len(ledger(engine)['charges'])==1 and engine.state.actors[A].resources[QI]==26
    assert engine.state.actors[B].current_hp<60
    assert any(c.condition_id=='condition:typed.vessel_no_heal' for c in engine.state.actors[B].conditions.values())


def test_walking_survived_types_overflow_cost_reaction_discount_and_origins(tmp_path,monkeypatch):
    cold,jid,_=game(tmp_path,monkeypatch,profiles=[hazard()])
    service,table,mid=fight(cold,jid,tmp_path);face(service,table,mid)
    settle(table,mid,candidate(service,mid,'Walking Tribulation').candidate_id,picks={'choice:vessel.spend':None})
    engine=loaded(cold,mid);d=ledger(engine)
    assert len(d['charges'])==5 and sum(c['overflow'] for c in d['charges'])==3
    assert d['walking']['remaining']==10 and engine.state.actors[A].resources[QI]==21
    assert any(c.metadata.get('effect_origin') for c in engine.legal_candidates() if engine.action_catalog[c.source_definition_id].display_name=='Tribulation Release')


def test_expired_wrong_authority_and_variant_access_reject_atomically(tmp_path,monkeypatch):
    cold,jid,world=game(tmp_path,monkeypatch,acquire=False)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):cold().journey_acquire_source(jid,before['revision'],A,P,{'access_scope':'missing'})
    assert cold().journey_state(jid)==before
    with pytest.raises(ValueError):cold().journey_act(jid,before['revision'],A,'declare_fact',{'source':P,'subject':A,'kind':'source_access','scope':'forged','value':{'route':'restricted_scripture','source_rule':'claimed'},'expires_at':100,'readers':[A]})
    assert cold().journey_state(jid)==before
