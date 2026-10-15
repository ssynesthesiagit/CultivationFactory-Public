"""Culinary native acquisition, paid work, finite batch and cold replay guards."""
import json
import zipfile
from pathlib import Path
import pytest
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
SCHOOL='tianxia.subpath.qi.culinary_cultivator'
MEAL=SCHOOL+'.feature.body_tempering_meal'
RATION=SCHOOL+'.feature.sealed_field_rations'
KEY='culinary:preparation'
COURSES=('iron_bone_stew','long_march_rice','bitter_herb_broth','furnace_spice_skewers','clear_fish_soup','festival_dumplings')

PIDS=['0badc0de-0000-4000-8000-000000000181','0badc0de-0000-4000-8000-000000000182']
A,B=[FACTORY_ACTOR_PREFIX+p for p in PIDS]


def game(tmp_path,cl=6):
    for pid in PIDS:
        doc=sheet([],cl=cl,primary='Qi');doc['identity']['path_ids']=['tianxia.path.qi_cultivation']
        doc['path_and_subpath']={'path_record_ids':['tianxia.path.qi_cultivation']}
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    def cold():return CombatService(ROOT,tmp_path)
    TabletopService(cold(),tmp_path).add_advancement(PIDS[0],'subpath',SCHOOL)
    acquired=cold()._factory_owner_sheet(PIDS[0])
    assert MEAL in acquired['path_and_subpath']['path_feature_record_ids']
    assert RATION in acquired['path_and_subpath']['path_feature_record_ids']
    cold().tabletop_maps.save({'map_id':'culinary','display_name':'Culinary','width_squares':10,'height_squares':10,
        'square_size_ft':5,'walls':[],'starts':{'team1':[[2,2]],'team2':[[2,3]]}})
    s=cold().create_journey(project_ids=PIDS,arena_id='battlefield:map.culinary',positions={A:{'x':2,'y':2},B:{'x':2,'y':3}},base_paces={A:1800,B:1800})
    jid=s['journey_id']
    def act(kind,payload=None,aid=A):
        s=cold().journey_state(jid)
        result=cold().journey_act(jid,s['revision'],aid,kind,payload or {})
        assert cold().journey_state(jid)==result
        assert cold().journey_verify(jid)['status']=='PASS'
        return result
    def fact(source,kind,scope,value,aid=A,seconds=86400):
        s=cold().journey_state(jid)
        result=cold().journey_world_fact(jid,s['revision'],{'source':source,'subject':aid,'kind':kind,'scope':scope,
            'value':value,'expires_at':s['seconds']+seconds,'readers':[aid]})
        assert cold().journey_verify(jid)['status']=='PASS'
        return result
    return cold,jid,act,fact


def food(act,fact):
    fact('system:journey.admission','material_source','food',{'payload':{'id':'food','name':'Ordinary grain and vegetables',
        'kind':'raw_material','context':'scene','material':'ordinary_food','unit':'creature_day','quantity':20,'known_to':[A],
        'exclusive_to':A},'provenance':'Actual caravan food inventory'},seconds=1)
    s=act('collect_material',{'source':'food','quantity':20})
    return next(iter(s['actors'][A]['material_holdings']))


def start(act,source,p):return act('activity_start',{'source':source,'parameters':p})


def test_rations_paid_work_split_destroy_and_expiry(tmp_path):
    cold,jid,act,fact=game(tmp_path)
    key=food(act,fact)
    before=cold().journey_state(jid)['actors'][A]['resources']['resource:core.qi']
    start(act,RATION,{'food':key,'rations':['restorative','bracing']})
    s=act('activity_work',{'seconds':599})
    assert not any(x['kind']=='prepared_consumable' for x in s['actors'][A]['material_holdings'].values())
    s=act('activity_work',{'seconds':1})
    assert s['actors'][A]['resources']['resource:core.qi']==before-2
    assert s['actors'][A]['material_holdings'][key]['quantity']==18
    batch=next(k for k,v in s['actors'][A]['material_holdings'].items() if v.get('preparation')=='sealed_restorative')
    expiry=s['actors'][A]['material_holdings'][batch]['expires_at']
    s=act('prepared_transfer',{'batch':batch,'quantity':1,'recipient':B})
    assert s['actors'][B]['material_holdings'][batch]['expires_at']==expiry
    with pytest.raises(ValueError):act('prepared_transfer',{'batch':batch,'quantity':1,'recipient':B})
    s=act('prepared_destroy',{'batch':batch,'quantity':1},B)
    assert s['actors'][B]['material_holdings'][batch]['quantity']==0
    assert cold().journey_verify(jid)['status']=='PASS'


def test_wrong_owner_default_inert_and_interruption(tmp_path):
    cold,jid,act,fact=game(tmp_path);key=food(act,fact)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):start(lambda k,p:act(k,p,B),RATION,{'food':key,'rations':['restorative']})
    assert cold().journey_state(jid)==before
    start(act,RATION,{'food':key,'rations':['restorative']})
    act('activity_work',{'seconds':300});s=act('wait',{'seconds':300})
    assert not any(v['kind']=='prepared_consumable' for v in s['actors'][A]['material_holdings'].values())
    with pytest.raises(ValueError):act('activity_work',{'seconds':300})


def test_meal_requires_recipient_consent_consumes_food_and_rest_ends(tmp_path):
    cold,jid,act,fact=game(tmp_path);key=food(act,fact)
    act('culinary_courses',{'courses':list(COURSES[:4])})
    p={'food':key,'servings':{B:'iron_bone_stew'},'rations':['bracing']*4}
    with pytest.raises(ValueError):start(act,MEAL,p)
    s=cold().journey_state(jid)
    act('declare_fact',{'source':MEAL,'subject':B,'kind':'willing','scope':A,'value':1,'expires_at':s['seconds']+86400,'readers':[A]},B)
    start(act,MEAL,p);s=act('activity_work',{'seconds':3600})
    assert s['actors'][B]['source_states'][KEY]['meal']['course']=='iron_bone_stew'
    assert s['actors'][A]['material_holdings'][key]['quantity']==19
    s=act('long_rest',{},B)
    assert 'meal' not in s['actors'][B]['source_states'][KEY]


def test_prepared_ration_real_combat_action_cold_reload_replay(tmp_path):
    cold,jid,act,fact=game(tmp_path);key=food(act,fact)
    start(act,RATION,{'food':key,'rations':['fortifying']})
    s=act('activity_work',{'seconds':600})
    mid=cold().journey_start_combat(jid,s['revision'],{A:'team:a',B:'team:b'},maximum_rounds=2)['match_id']
    table=TabletopService(cold(),tmp_path)
    for _ in range(6):
        view=table.state(mid)
        if view['menu']['actor_id']==A:break
        assert table.act(mid,view['menu']['end_turn'],view['menu']['decision_id'],view['menu']['state_version'],view['last_sequence'])['status']=='COMMITTED'
        table=TabletopService(cold(),tmp_path)
    view=table.state(mid)
    group=next(g for g in view['menu']['actions'] if g['label']=='Consume Fortifying Ration')
    candidate=group['options'][0]['candidate_id']
    result=table.act(mid,candidate,view['menu']['decision_id'],view['menu']['state_version'],view['last_sequence'])
    assert result['status']=='COMMITTED'
    actor=cold()._load_session(mid).engine.state.actors[A]
    assert actor.temporary_hp>0
    assert actor.resources['resource:named.sealed_field_ration.0']==0
    assert cold().verify(mid)['status']=='PASS'
    assert cold().replay(mid)['status']=='PASS'
