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


@pytest.fixture(scope='module',autouse=True)
def exact_owner_source():
    import hashlib
    rules=json.loads((ROOT/'authority/typed_mechanics/rules_text.json').read_text())
    assert hashlib.sha256(rules[MEAL].encode()).hexdigest()=='d9ab010d1981815800478a0d56c22b2b1449358a6463af252abe44817a6d449a'
    assert hashlib.sha256(rules[RATION].encode()).hexdigest()=='941d2e6ddcb32e331ce5ddd06e6c5ea3bbfd07cf7afc6a40920ee947300240a6'


def game(tmp_path,cl=6,*,acquire=True,pace=1800):
    for pid in PIDS:
        doc=sheet([],cl=cl,primary='Qi',key='INT',dc=8+(2+(cl-1)//4)+2)
        doc['identity']['proficiency_bonus']=2+(cl-1)//4
        stats=doc['ability_scores_and_statistics']
        stats['primary_resource']['maximum']=2*cl
        stats['technique_attack_bonus']=doc['identity']['proficiency_bonus']+2
        stats['hit_points']['maximum']=10+7*(cl-1)
        stats['armor_class']['base_value']=12
        doc['identity']['path_ids']=['tianxia.path.qi_cultivation']
        doc['path_and_subpath']={'path_record_ids':['tianxia.path.qi_cultivation']}
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    def cold():return CombatService(ROOT,tmp_path)
    if acquire:
        from canonical_catalog.service import CanonicalCatalogAuthorityService
        table=TabletopService(cold(),tmp_path)
        table.canonical_catalog=CanonicalCatalogAuthorityService(ROOT)
        table.add_advancement(PIDS[0],'subpath',SCHOOL)
        acquired=cold()._factory_owner_sheet(PIDS[0])
        assert MEAL in acquired['path_and_subpath']['path_feature_record_ids']
        assert RATION in acquired['path_and_subpath']['path_feature_record_ids']
    cold().tabletop_maps.save({'map_id':'culinary','display_name':'Culinary','width_squares':10,'height_squares':10,
        'square_size_ft':5,'walls':[],'starts':{'team1':[[2,2]],'team2':[[2,3]]}})
    s=cold().create_journey(project_ids=PIDS,arena_id='battlefield:map.culinary',positions={A:{'x':2,'y':2},B:{'x':2,'y':3}},base_paces={A:pace,B:pace})
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


def food(act,fact,*,meal=False):
    fact('system:journey.admission','material_source','food',{'payload':{'id':'food','name':'Ordinary grain and vegetables',
        'kind':'raw_material','context':'scene','material':'ordinary_food','unit':'creature_day' if meal else 'ration_ingredient_portion','quantity':20,'known_to':[A],
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
    cold,jid,act,fact=game(tmp_path);key=food(act,fact,meal=True)
    act('culinary_courses',{'courses':list(COURSES[:4])})
    p={'food':key,'servings':{B:'iron_bone_stew'},'rations':['bracing']*3}
    with pytest.raises(ValueError):start(act,MEAL,p)
    s=cold().journey_state(jid)
    act('declare_fact',{'source':MEAL,'subject':B,'kind':'willing','scope':A,'value':1,'expires_at':s['seconds']+86400,'readers':[A]},B)
    start(act,MEAL,p);s=act('activity_work',{'seconds':3600})
    assert 'meal' not in s['actors'][B]['source_states'][KEY]
    s=act('culinary_eat',{},B)
    with pytest.raises(ValueError):act('culinary_eat',{},B)
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
    for _ in range(10):
        engine=cold()._load_session(mid).engine
        if engine.state.terminal_result:break
        table=TabletopService(cold(),tmp_path);view=table.state(mid)
        assert table.act(mid,view['menu']['end_turn'],view['menu']['decision_id'],view['menu']['state_version'],view['last_sequence'])['status']=='COMMITTED'
    engine=cold()._load_session(mid).engine
    assert engine.state.terminal_result
    bound=cold().journey_state(jid)
    resumed=cold().journey_resume(jid,bound['revision'])
    assert resumed['seconds']==612  # two actual rounds; the limit sentinel is not a third round
    assert all(v['quantity']==0 for v in resumed['actors'][A]['material_holdings'].values() if v.get('preparation')=='sealed_fortifying')
    assert cold().journey_verify(jid)['status']=='PASS'
    assert cold().verify(mid)['status']=='PASS'
    assert cold().replay(mid)['status']=='PASS'


@pytest.mark.parametrize('elapsed',[86399,86400])
def test_spent_expired_and_bad_count_cannot_produce_new_portions(tmp_path,elapsed):
    cold,jid,act,fact=game(tmp_path);key=food(act,fact)
    original=cold().journey_state(jid)
    for kinds in ([],['bracing']*4,['invented']):
        with pytest.raises(ValueError):start(act,RATION,{'food':key,'rations':kinds})
        assert cold().journey_state(jid)==original
    start(act,RATION,{'food':key,'rations':['bracing']})
    act('activity_work',{'seconds':600})
    s=act('wait',{'seconds':elapsed})
    mid=cold().journey_start_combat(jid,s['revision'],{A:'team:a',B:'team:b'},maximum_rounds=1)['match_id']
    engine=cold()._load_session(mid).engine
    present=any(a.display_name=='Consume Bracing Ration' for a in engine.action_catalog.values())
    assert present==(elapsed==86399)
    if present:
        for _ in range(2):
            table=TabletopService(cold(),tmp_path);view=table.state(mid)
            if view['menu']['actor_id']==A:break
            assert table.act(mid,view['menu']['end_turn'],view['menu']['decision_id'],view['menu']['state_version'],view['last_sequence'])['status']=='COMMITTED'
        group=next(g for g in view['menu']['actions'] if g['label']=='Consume Bracing Ration')
        assert table.act(mid,group['options'][0]['candidate_id'],view['menu']['decision_id'],view['menu']['state_version'],view['last_sequence'])['status']=='COMMITTED'
        assert cold()._load_session(mid).engine.state.actors[A].resources['resource:named.sealed_field_ration.0']==0
    assert cold().verify(mid)['status']=='PASS' and cold().replay(mid)['status']=='PASS'


def test_ordinary_journey_continuation_clock_and_inventory_are_default_inert(tmp_path):
    cold,jid,act,fact=game(tmp_path,acquire=False)
    s=cold().journey_state(jid)
    mid=cold().journey_start_combat(jid,s['revision'],{A:'team:a',B:'team:b'},maximum_rounds=1)['match_id']
    for _ in range(6):
        engine=cold()._load_session(mid).engine
        if engine.state.terminal_result:break
        table=TabletopService(cold(),tmp_path);view=table.state(mid)
        assert table.act(mid,view['menu']['end_turn'],view['menu']['decision_id'],view['menu']['state_version'],view['last_sequence'])['status']=='COMMITTED'
    assert cold()._load_session(mid).engine.state.terminal_result
    bound=cold().journey_state(jid)
    resumed=cold().journey_resume(jid,bound['revision'])
    assert resumed['seconds']==0
    assert not any('material_holdings' in row or KEY in row.get('source_states',{}) for row in resumed['actors'].values())
    assert cold().verify(mid)['status']=='PASS' and cold().replay(mid)['status']=='PASS'


def test_native_consumed_stew_projects_once_and_survives_two_encounters(tmp_path):
    cold,jid,act,fact=game(tmp_path);key=food(act,fact,meal=True)
    act('culinary_courses',{'courses':list(COURSES[:4])})
    s=cold().journey_state(jid)
    act('declare_fact',{'source':MEAL,'subject':B,'kind':'willing','scope':A,'value':1,
        'expires_at':s['seconds']+86400,'readers':[A]},B)
    start(act,MEAL,{'food':key,'servings':{B:'iron_bone_stew'},'rations':['bracing']*3})
    s=act('activity_work',{'seconds':3600})
    base=s['actors'][B]['bundle']['actor_template']['maximum_hp']
    s=act('culinary_eat',{},B)
    expected=base+6
    for _ in range(2):
        mid=cold().journey_start_combat(jid,s['revision'],{A:'team:a',B:'team:b'},maximum_rounds=1)['match_id']
        creature=cold()._load_session(mid).engine.state.actors[B]
        assert creature.maximum_hp==expected and creature.current_hp==expected
        assert any(c.condition_id=='condition:typed.iron_bone_stew' for c in creature.conditions.values())
        for _ in range(6):
            if cold()._load_session(mid).engine.state.terminal_result:break
            table=TabletopService(cold(),tmp_path);view=table.state(mid)
            assert table.act(mid,view['menu']['end_turn'],view['menu']['decision_id'],view['menu']['state_version'],view['last_sequence'])['status']=='COMMITTED'
        assert cold().verify(mid)['status']=='PASS' and cold().replay(mid)['status']=='PASS'
        bound=cold().journey_state(jid);s=cold().journey_resume(jid,bound['revision'])
        assert cold().journey_verify(jid)['status']=='PASS'
    s=act('long_rest',{},B)
    assert 'meal' not in s['actors'][B]['source_states'][KEY]


def test_fractional_native_movement_does_not_expire_food_early(tmp_path):
    cold,jid,act,fact=game(tmp_path,pace=1801);key=food(act,fact)
    act('move',{'path':[{'x':3,'y':2}]})
    start(act,RATION,{'food':key,'rations':['fortifying']})
    act('activity_work',{'seconds':600})
    act('wait',{'seconds':86390})
    s=act('move',{'path':[{'x':4,'y':2}]})
    assert s['subsecond_num']>0
    mid=cold().journey_start_combat(jid,s['revision'],{A:'team:a',B:'team:b'},maximum_rounds=1)['match_id']
    for _ in range(2):
        table=TabletopService(cold(),tmp_path);view=table.state(mid)
        if view['menu']['actor_id']==A:break
        assert table.act(mid,view['menu']['end_turn'],view['menu']['decision_id'],view['menu']['state_version'],view['last_sequence'])['status']=='COMMITTED'
    group=next(g for g in view['menu']['actions'] if g['label']=='Consume Fortifying Ration')
    assert table.act(mid,group['options'][0]['candidate_id'],view['menu']['decision_id'],view['menu']['state_version'],view['last_sequence'])['status']=='COMMITTED'
    assert cold()._load_session(mid).engine.state.actors[A].temporary_hp>0
    assert cold().verify(mid)['status']=='PASS' and cold().replay(mid)['status']=='PASS'


def test_finish_and_new_journey_preserve_remaining_physical_food_lifetime(tmp_path):
    cold,jid,act,fact=game(tmp_path);key=food(act,fact)
    start(act,RATION,{'food':key,'rations':['bracing']})
    act('activity_work',{'seconds':600});act('wait',{'seconds':86399})
    act('finish')
    s=cold().create_journey(project_ids=PIDS,arena_id='battlefield:map.culinary',
        positions={A:{'x':2,'y':2},B:{'x':2,'y':3}},base_paces={A:1800,B:1800})
    next_jid=s['journey_id']
    s=cold().journey_act(next_jid,s['revision'],A,'wait',{'seconds':1})
    assert cold().journey_verify(next_jid)['status']=='PASS'
    mid=cold().journey_start_combat(next_jid,s['revision'],{A:'team:a',B:'team:b'},maximum_rounds=1)['match_id']
    assert not any(a.display_name=='Consume Bracing Ration' for a in cold()._load_session(mid).engine.action_catalog.values())
    assert cold().verify(mid)['status']=='PASS' and cold().replay(mid)['status']=='PASS'
