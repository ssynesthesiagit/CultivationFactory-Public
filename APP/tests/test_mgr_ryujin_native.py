"""Native acquisition -> journey -> table intent -> cold mechanical replay."""
import json
import zipfile
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import candidate, settle, turn
P='tianxia.subpath.body.ryujin'; R=P+'.feature.'
A='actor:factory.dragon'; B='actor:factory.partner'; C='actor:factory.opponent'
STAMINA='resource:core.stamina'
MILESTONES=[(3,'dragon_scales'),(6,'dragon_s_breath'),(10,'storm_step'),(14,'dragon_s_roar'),(18,'ryujin_ascendant_form')]


def access(service,jid):
    state=service.journey_state(jid)
    return service.journey_world_fact(jid,state['revision'],{'source':P,'subject':A,'kind':'source_access','scope':'inheritance',
        'value':{'category':'Rare Inheritance','source_rule':'GM establishes inherited Ryujin bloodline'},'expires_at':3600,'readers':[A]})


def game(tmp_path,*,cl=18,acquire=True,path='tianxia.path.body_refining',attainment=None):
    for pid in ('dragon','partner','opponent'):
        doc=sheet([],cl=cl,primary='Stamina',name=pid.title(),dc=50)
        doc['identity']['path']='Body Refining'
        doc['ability_scores_and_statistics']['hit_points']['maximum']=1000
        doc['ability_scores_and_statistics']['primary_resource']['maximum']=100
        doc['path_and_subpath']={'path_record_id':path,'path_record_ids':[path],
            'paths':[{'path_id':path,'attainment':cl if attainment is None else attainment}],
            'path_feature_record_ids':['tianxia.path.body_refining.feature.unarmored_defense']}
        doc['ability_scores_and_statistics']['armor_class']={'base_value':14,
            'generation':{'calculation_feature_id':'tianxia.path.body_refining.feature.unarmored_defense'}}
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    service=CombatService(ROOT,tmp_path)
    service.tabletop_maps.save({'display_name':'Ryujin yard','width_squares':12,'height_squares':12,'walls':[],
        'starts':{'team1':[[3,6],[5,7]],'team2':[[5,6]]}})
    state=service.create_journey(project_ids=['dragon','partner','opponent'],arena_id='battlefield:map.ryujin-yard',
        positions={A:{'x':3,'y':6},B:{'x':5,'y':7},C:{'x':5,'y':6}},base_paces={a:100 for a in (A,B,C)},control_modes={a:'MANUAL' for a in (A,B,C)})
    jid=state['journey_id']
    if acquire:
        state=access(service,jid)
        state=service.journey_act(jid,state['revision'],A,'declare_fact',{'source':P,'subject':A,'kind':'anatomy','scope':'body',
            'value':{'breath_organ':'mouth','scales':'concealable'},'expires_at':3600,'readers':[A]})
        state=service.journey_acquire_source(jid,state['revision'],A,P,{'access_scope':'inheritance','anatomy_scope':'body'})
    return service,jid,state


def fight(service,jid,tmp_path):
    state=service.journey_state(jid)
    mid=service.journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:a',C:'team:b'})['match_id']
    service=CombatService(ROOT,tmp_path);table=TabletopService(service,tmp_path);turn(table,mid,A)
    return service,table,mid


def cold(tmp_path,mid):
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status']=='PASS'
    return loaded.engine


@pytest.mark.parametrize('cl',[2,3,6,10,14,18])
def test_native_acquisition_progression_and_wrong_owner(tmp_path,cl):
    if cl<3:
        service,jid,state=game(tmp_path,cl=cl,acquire=False);access(service,jid);state=service.journey_state(jid)
        with pytest.raises(ValueError):service.journey_acquire_source(jid,state['revision'],A,P,{'access_scope':'inheritance','anatomy_scope':'body'})
        assert service.journey_state(jid)==state
        return
    service,jid,state=game(tmp_path,cl=cl)
    assert state['actors'][A]['source_states'][P]['features']==[R+n for l,n in MILESTONES if l<=cl]
    assert 'source_states' not in state['actors'][B]
    service,table,mid=fight(service,jid,tmp_path);engine=cold(tmp_path,mid)
    sources={a.parameters.get('typed',{}).get('source') for a in engine.action_catalog.values() if a.owner_id==A}
    assert {R+n for l,n in MILESTONES if 3<l<=cl}<=sources
    assert not any(a.parameters.get('typed',{}).get('source','').startswith(R) for a in engine.action_catalog.values() if a.owner_id==B)


def test_breath_and_roar_native_commit_save_damage_reload(tmp_path):
    service,jid,_=game(tmp_path);service,table,mid=fight(service,jid,tmp_path)
    for name,cost in [("Dragon's Breath",2),("Dragon's Roar",5)]:
        before=cold(tmp_path,mid).state.actors[A].resources[STAMINA]
        settle(table,mid,candidate(service,mid,name,at=(5,6)).candidate_id,choices={'choice:needle.ryujin_damage':['THUNDER']})
        engine=cold(tmp_path,mid);assert engine.state.actors[A].resources[STAMINA]==before-cost
        for target in (B,C):assert any(e.event_type=='DAMAGE_COMMITTED' and target in e.target_ids for e in engine.events)
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={});turn(table,mid,A)


def test_ascendant_native_profiles_flight_size_and_step(tmp_path):
    from combat.flight import profile
    from combat import dynamic_size
    service,jid,_=game(tmp_path);service,table,mid=fight(service,jid,tmp_path)
    settle(table,mid,candidate(service,mid,'Ryūjin Ascendant Form').candidate_id,choices={'choice:needle.ryujin_size':['large']})
    engine=cold(tmp_path,mid);actor=engine.state.actors[A]
    assert actor.resources[STAMINA]==93
    assert profile(engine,actor).speed_ft==60 and profile(engine,actor).hover
    assert dynamic_size.current_category(engine,actor)=='Large'
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={});turn(table,mid,A)
    settle(table,mid,candidate(service,mid,'Storm Step (Ascendant)').candidate_id,
        choices={'choice:needle.teleport_destination':['cell:6,6'],'choice:needle.ryujin_damage':['LIGHTNING'],'choice:needle.storm_recipients':[C]})
    engine=cold(tmp_path,mid)
    assert engine.state.actors[A].resources[STAMINA]==92 and engine.state.actors[A].position.x==6
