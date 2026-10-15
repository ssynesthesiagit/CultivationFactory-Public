"""Native learning -> authoritative source input -> table -> cold reload/replay."""
import json, zipfile
from hashlib import sha256
import pytest
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.factory_compiler import compile_character
from factory_authoring import path_access
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT,sheet
from tests.worker2_support import settle,turn,reload
OWNER="actor:factory.aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ALLY="actor:factory.bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
FOE="actor:factory.cccccccc-cccc-cccc-cccc-cccccccccccc"

QI='HUNGER_BASE_TASTE_THE_QI';TRACE='INK_BASE_READ_THE_TRACE';VESSEL='IMBUEMENT_BASE_READ_THE_VESSEL'
VENOM='POISON_BASE_APPRAISE_THE_VENOM';METAL='METAL_BASE_METAL_APPRAISAL';SKY='WEATHER_BASE_READ_THE_SKY'
PATH_ACCESS_SOURCE='APP/authority/Tianxia_Sphere_Path_Access_R1.json'
PATH_ACCESS_SHA256='359659f5b0388353a6604443b46b29dc8ad549044d0a8c39ff34f8e8525c9f5e'
SPHERES={QI:'hunger',TRACE:'ink',VESSEL:'imbuement',VENOM:'poison',METAL:'metal',SKY:'weather'}

def source(subject,values):
    return {'subject_id':subject,'facts':{k:{'value':v} for k,v in values.items() if k not in {'qi.unwilling','qi.concealing'}}}

def make(tmp_path,row,values=None,*,subject=FOE,own=True,position=None,objects=None,source_rows=None,blind=False,extra_foe=False,fragile_foe=False,talent=None,kit=None):
    ids=[OWNER,ALLY,FOE]+(['actor:factory.dddddddd-dddd-dddd-dddd-dddddddddddd'] if extra_foe else [])
    for aid in ids:
        doc=sheet([],cl=15,kit=kit,name={OWNER:'Wren',ALLY:'Tobin',FOE:'Mara'}.get(aid,'Guard'))
        if aid==FOE and fragile_foe:doc['ability_scores_and_statistics']['hit_points']['maximum']=1
        doc['identity']['path_ids']=['tianxia.path.qi_cultivation']
        doc['path_and_subpath']={'path_record_id':'tianxia.path.qi_cultivation','path_record_ids':['tianxia.path.qi_cultivation']}
        doc['ability_scores_and_statistics']['primary_resource']['maximum']=100
        folder=tmp_path/'portable_characters'/aid.removeprefix('actor:factory.');folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    assert sha256((ROOT.parent/PATH_ACCESS_SOURCE).read_bytes()).hexdigest()==PATH_ACCESS_SHA256
    path_access.access()  # real native learning authority, never a mocked grant
    combat=CombatService(ROOT,tmp_path);table=TabletopService(combat,tmp_path)
    table.canonical_catalog=CanonicalCatalogAuthorityService(ROOT)
    if own:table.add_advancement(OWNER.removeprefix('actor:factory.'),'sphere','tianxia.sphere.'+SPHERES[row])
    if talent:table.add_advancement(OWNER.removeprefix('actor:factory.'),'talent',talent)
    if blind:
        table.add_advancement(ALLY.removeprefix('actor:factory.'),'sphere','tianxia.sphere.dark')
        table.add_advancement(ALLY.removeprefix('actor:factory.'),'talent','TAL_DARK_BLINDFOLD')
    bundles=[compile_character(combat._factory_owner_sheet(a.removeprefix('actor:factory.')),actor_id=a,reaction_plan={'ask':True}) for a in ids]
    from copy import deepcopy
    arena=deepcopy(combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'])
    if objects:arena['map_objects']=objects
    mid=combat._finish_factory_match(bundles,ids,{a:'team:factory' if a in (OWNER,ALLY) else 'team:opponents' for a in ids},
        {OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:position or {'x':4,'y':6},**({ids[-1]:{'x':7,'y':6}} if extra_foe else {})},arena,[OWNER,ALLY],ids[2:],
        control_modes={a:'MANUAL' for a in ids},match_seed='KNOWLEDGE',display_name='Knowledge',maximum_rounds=15,
        source_inputs=source_rows(bundles) if callable(source_rows) else source_rows if source_rows is not None else [source(subject,values)] if values else None)['match_id']
    turn(table,mid,OWNER)
    return combat,table,mid

def candidates(combat,mid,row,subject=None,suffix=None):
    e=combat._load_session(mid).engine
    return [c for c in e.legal_candidates() if (a:=e.action_catalog.get(c.source_definition_id)) and
        (a.parameters.get('typed') or {}).get('source')==row and
        (subject is None or c.target_ids==(subject,) or c.metadata.get('object_id')==subject) and
        (suffix is None or suffix in a.display_name)]

def answers(tmp_path,mid):
    e=reload(tmp_path,mid)
    return [c.data for c in e.state.actors[OWNER].conditions.values() if c.condition_id=='condition:information.reading']

@pytest.mark.parametrize('row,question,extra,expected',[
 (QI,'qi.expression',{'qi.expression':'Obvious cold qi'},'Obvious cold qi'),
 (TRACE,'trace.hand',{'subject.kind':'inscription','trace.hand':'A spirit'},'A spirit'),
 (VESSEL,['vessel.safe','vessel.resists'],{'vessel.dc':0,'vessel.safe':'Light','vessel.resists':'Weight'},'Light'),
 (VENOM,'poison.kind',{'poison.present':True,'poison.kind':'Mineral'},'Mineral'),
 (METAL,'metal.properties',{'metal.bearing':True,'metal.properties':'Resonant'},'Resonant')])
def test_native_acquisition_source_table_cold_replay(tmp_path,row,question,extra,expected):
    combat,table,mid=make(tmp_path,row,extra)
    rows=candidates(combat,mid,row,FOE);assert rows,'Printed target must be reachable after learning the sphere'
    settle(table,mid,rows[0].candidate_id,picks={'choice:needle.reading_questions':question})
    assert expected in json.dumps(answers(tmp_path,mid))
    e=reload(tmp_path,mid)
    assert not [c for c in e.state.actors[ALLY].conditions.values() if c.condition_id=='condition:information.reading']
    assert expected not in json.dumps(table.events(mid,0))
    assert not (e.state.actors[OWNER].bonus_action_available if row==QI else e.state.actors[OWNER].action_available)

@pytest.mark.parametrize('row',list(SPHERES))
def test_wrong_owner_default_inert(tmp_path,row):
    combat,table,mid=make(tmp_path,row,own=False)
    assert not candidates(combat,mid,row)
    assert answers(tmp_path,mid)==[]

def test_unknown_and_unauthorized_input(tmp_path):
    combat,table,mid=make(tmp_path,QI)
    settle(table,mid,candidates(combat,mid,QI,FOE)[0].candidate_id,picks={'choice:needle.reading_questions':'qi.ward'})
    assert 'Unknown' in json.dumps(answers(tmp_path,mid))
    from combat.encounter_sources import prepare
    with pytest.raises(ValueError,match='unauthorized'):
        prepare(combat._load_session(mid).engine.battlefield_document,[source(FOE,{'secret.stat_block':'all'})],[OWNER,ALLY,FOE])
    invalid=source(FOE,{'qi.expression':'cold'});invalid.update(authority_role='actor',authority_actor_id=FOE)
    with pytest.raises(ValueError,match='submitted authority role'):
        prepare(combat._load_session(mid).engine.battlefield_document,[invalid],[OWNER,ALLY,FOE])

@pytest.mark.parametrize('distance,allowed',[(30,True),(35,False)])
def test_range_boundary(tmp_path,distance,allowed):
    combat,table,mid=make(tmp_path,QI,position={'x':3+distance//5,'y':6})
    assert bool(candidates(combat,mid,QI,FOE))==allowed

def test_vessel_failed_check_private(tmp_path):
    combat,table,mid=make(tmp_path,VESSEL,{'vessel.dc':1000,'vessel.safe':'Hidden answer','vessel.resists':'Another hidden answer'})
    settle(table,mid,candidates(combat,mid,VESSEL,FOE)[0].candidate_id,picks={'choice:needle.reading_questions':['vessel.safe','vessel.resists']})
    assert 'Hidden answer' not in json.dumps(answers(tmp_path,mid))
    assert answers(tmp_path,mid)[-1]['details']['check_failed']==1

def test_venom_paid_three_and_profile(tmp_path):
    combat,table,mid=make(tmp_path,VENOM,{'poison.present':True,'poison.kind':'Spiritual','poison.timing':'Delayed','poison.antidote':False})
    rows=candidates(combat,mid,VENOM,FOE,suffix='three facts');assert rows
    settle(table,mid,rows[0].candidate_id,picks={'choice:needle.reading_questions':['poison.kind','poison.timing','poison.antidote'],'choice:needle.reading_profile':'create'})
    assert reload(tmp_path,mid).state.actors[OWNER].resources['resource:core.qi']==99
    assert 'Antidote Profile' in json.dumps(answers(tmp_path,mid))
    assert len(answers(tmp_path,mid)[0]['details']['answers'])==4

def test_weather_current_categories_origin(tmp_path):
    values={'weather.air':True,'weather.categories':dict.fromkeys(['wind','precipitation','cold','heat','aridity','storm'],0),
        'weather.categories_radius_ft':5280,'weather.origin':['natural'],'weather.origin_radius_ft':300}
    combat,table,mid=make(tmp_path,SKY,values,subject='scene')
    settle(table,mid,candidates(combat,mid,SKY)[0].candidate_id)
    assert 'natural' in json.dumps(answers(tmp_path,mid)) and 'precipitation' in json.dumps(answers(tmp_path,mid))

@pytest.mark.parametrize('row,kind,question,expected',[
 (QI,'ingredient','qi.impurity','Yes'),(TRACE,'inscription','trace.age','Written recently'),
 (VESSEL,'weapon',['vessel.safe','vessel.nature'],'Spiritual'),
 (VENOM,'sample','poison.kind','Alchemical'),(METAL,'ore','metal.material','iron')])
def test_native_mapped_sources_all_appraisals(tmp_path,row,kind,question,expected):
    values={'subject.kind':kind,'qi.impurity':True,'trace.age':'Written recently','vessel.dc':0,
        'vessel.safe':'Light','vessel.nature':'Spiritual','poison.present':True,'poison.kind':'Alchemical'}
    combat,table,mid=make(tmp_path,row,values,subject='object:map.601',objects=[{'id':601,'kind':'custom','material':'iron','x':4,'y':7,'blocks':False}])
    offered=candidates(combat,mid,row,'object:map.601');assert offered
    settle(table,mid,offered[0].candidate_id,picks={'choice:needle.reading_questions':question})
    assert str(expected).lower() in json.dumps(answers(tmp_path,mid)).lower()

@pytest.mark.parametrize('sign',['wind','rain','cold','heat','dry','thunder'])
def test_shroud_starting_sign_is_real_choice_and_object_outcome_replays(tmp_path,sign):
    combat,table,mid=make(tmp_path,SKY,{'weather.vulnerable.'+sign:True,'weather.object_effect.'+sign:'frozen'},subject='object:map.601',
        objects=[{'id':601,'kind':'custom','material':'iron','x':4,'y':7,'blocks':False}])
    offered=candidates(combat,mid,'WEATHER_BASE_CLOUD_SHROUD','object:map.601');assert offered
    prompts=settle(table,mid,offered[0].candidate_id,picks={'choice:needle.acquisition_weather_starting_sign':sign,
        'choice:needle.weather_shroud_sign':sign,'choice:needle.reading_battle_sign':sign})
    e=reload(tmp_path,mid);obj=e.state.objects['object:map.601']
    assert obj.component['cloud_shroud']['sign']==sign and obj.component['weather_state']=='frozen'
    assert e.state.actors[OWNER].resources['resource:core.qi']==99
    assert any(p['context']['reaction_source_id']=='choice:needle.acquisition_weather_starting_sign' for p in prompts)
    from combat.acquisition_choices import recorded
    assert recorded(e.state.actors[OWNER],'WEATHER_BASE_CLOUD_SHROUD','weather_starting_sign')==sign

@pytest.mark.parametrize('ability',['CHA','CON'])
def test_qi_contest_uses_gm_selected_native_save(tmp_path,ability):
    combat,table,mid=make(tmp_path,QI,{'qi.unwilling':True,'qi.concealing':True,'qi.defense':ability,
        'qi.expression':'Obvious cold qi','qi.fallback':'nourishing'})
    settle(table,mid,candidates(combat,mid,QI,FOE)[0].candidate_id,picks={'choice:needle.reading_questions':'qi.expression','choice:needle.fact_admission.qi_nature':'unwilling_concealed'})
    e=reload(tmp_path,mid)
    rolled=[r for r in e.events if r.event_type=='SAVE_ROLLED' and r.actor_id==FOE]
    assert rolled and rolled[-1].payload['reason'].endswith(':'+ability)
    result=answers(tmp_path,mid)[-1]['details']
    assert 'nourishing' in json.dumps(result) if result['check_failed'] else 'Obvious cold qi' in json.dumps(result)

def test_weather_learning_choice_persists_in_character_and_compiled_menu(tmp_path):
    combat,table,mid=make(tmp_path,SKY,own=False)
    pid=OWNER.removeprefix('actor:factory.')
    table.add_advancement(pid,'sphere','tianxia.sphere.weather',choices={'weather_starting_sign':['cold']})
    sheet_now=CombatService(ROOT,tmp_path)._factory_owner_sheet(pid)
    assert sheet_now['acquisition_choices']['tianxia.sphere.weather']['weather_starting_sign']==['cold']
    for _ in range(2):
        bundle=compile_character(sheet_now,actor_id=OWNER)
        actions=[a for a in bundle['action_catalog'] if a.get('parameters',{}).get('typed',{}).get('source')=='WEATHER_BASE_CLOUD_SHROUD']
        assert actions and all(a['parameters']['typed']['known_weather_signs']==['cold'] for a in actions)
    with pytest.raises(Exception,match='printed number'):
        table.add_advancement(ALLY.removeprefix('actor:factory.'),'sphere','tianxia.sphere.weather',choices={'weather_starting_sign':['cold','heat']})

@pytest.mark.parametrize('row', [QI,TRACE,VESSEL,VENOM,METAL])
def test_complete_printed_question_menu_and_answers_survive_each_commit(tmp_path,row):
    from combat.ext.knowledge_readings import QUESTIONS,LABELS,questions_for
    values={'subject.kind':'inscription' if row==TRACE else 'creature','metal.bearing':True,
        'qi.unwilling':False,'qi.concealing':False,'qi.nature':'Beast-born','qi.expression':'Cold qi','qi.impurity':False,'qi.ward':'Preservation seal',
        'trace.nature':'Spiritual','trace.contents':'Hidden script','trace.age':'Long ago','trace.hand':'A living hand','trace.alteration':'Overwritten',
        'trace.concealed':True,'trace.dc':0,
        'vessel.dc':0,'vessel.mandate':True,'vessel.safe':'Weight','vessel.resists':'Speed','vessel.nature':'Awakened',
        'vessel.bonus':'Suppressed bonus','vessel.enhancement':'Sense enhancement','vessel.backlash':False,
        'poison.present':True,'poison.kind':'Spiritual','poison.timing':'Long-term','poison.antidote':False,'poison.safe':False,'poison.sphere':'Alchemy',
        'metal.material':'Iron','metal.nature':'Oath-bound','metal.structure':'Reinforced','metal.properties':'Magnetic'}
    combat,table,mid=make(tmp_path,row,values)
    questions=questions_for(row,'inscription' if row==TRACE else 'creature');chunks=[questions[i:i+2] for i in range(0,len(questions),2)] if row==VESSEL else [[q] for q in questions]
    for index,chunk in enumerate(chunks):
        if len(chunk)==1 and row==VESSEL:chunk.append(questions[0])
        if index:
            settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
        prompts=settle(table,mid,candidates(combat,mid,row,FOE)[0].candidate_id,picks={'choice:needle.reading_questions':chunk})
        question=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.reading_questions')
        assert {o['id'] for o in question['choice']['options']}==set(questions)
        result=answers(tmp_path,mid)[-1]['details']['answers']
        assert all(LABELS[q] in result for q in chunk)

def journey(combat,values,subject='scene'):
    return combat.create_journey(project_ids=[OWNER.removeprefix('actor:factory.'),ALLY.removeprefix('actor:factory.')],
        arena_id='battlefield:map.builtin-sect-trial-platform',positions={OWNER:{'x':4,'y':5},ALLY:{'x':4,'y':6}},
        base_paces={OWNER:5,ALLY:5},source_inputs=[source(subject,values)] if values else None)

@pytest.mark.parametrize('interference',[False,True])
def test_careful_weather_actual_ten_minutes_cold_replay_and_interference(tmp_path,interference):
    combat,table,mid=make(tmp_path,SKY)
    categories=dict.fromkeys(['wind','precipitation','cold','heat','aridity','storm'],0)
    state=journey(combat,{'weather.forecast':[{'hour':0,'categories':categories},{'hour':48,'categories':categories}],
        'weather.forecast_radius_ft':26400,'weather.interference':interference})
    jid=state['journey_id']
    state=combat.journey_act(jid,0,OWNER,'information_weather',{'mode':'careful'})
    assert state['seconds']==600
    fresh=CombatService(ROOT,tmp_path)
    assert fresh.journey_state(jid,viewer_id=OWNER)==state and fresh.journey_replay(jid)['status']=='PASS'
    result=fresh.journey_menu(jid,OWNER)['properties']['information']
    assert ('Unknown' in json.dumps(result))==interference
    assert 'information' not in fresh.journey_menu(jid,ALLY)['properties']

@pytest.mark.parametrize('row,question,values,seconds',[
 (QI,['qi.expression'],{'qi.expression':'Cold qi','qi.unwilling':False,'qi.concealing':False},0),
 (TRACE,['trace.hand'],{'subject.kind':'inscription','trace.hand':'A spirit','trace.concealed':True,'trace.dc':0},0),
 (VESSEL,['vessel.safe','vessel.resists'],{'vessel.dc':0,'vessel.safe':'Light','vessel.resists':'Weight'},60),
 (VENOM,['poison.kind'],{'poison.present':True,'poison.kind':'Alchemical'},0),
 (METAL,['metal.properties'],{'metal.bearing':True,'metal.properties':'Magnetic'},0)])
def test_outside_combat_native_examination_cold_mechanical_replay(tmp_path,row,question,values,seconds):
    combat,table,mid=make(tmp_path,row)
    state=journey(combat,values,ALLY);jid=state['journey_id']
    if row==QI:
        state=combat.journey_act(jid,state['revision'],ALLY,'information_self_declaration',{'unwilling':False,'concealing':False})
    payload={'source':row,'subject_id':ALLY,'questions':question}
    if row==VESSEL:payload['mode']='One minute examination'
    state=combat.journey_act(jid,state['revision'],OWNER,'information_reading',payload)
    fresh=CombatService(ROOT,tmp_path)
    assert fresh.journey_state(jid,viewer_id=OWNER)==state and state['seconds']==seconds
    assert fresh.journey_replay(jid)['status']=='PASS'
    assert fresh.journey_menu(jid,OWNER)['properties']['information']
    if row==QI:
        state=fresh.journey_act(jid,state['revision'],OWNER,'wait',{'seconds':60})
        assert 'information' not in CombatService(ROOT,tmp_path).journey_menu(jid,OWNER)['properties']
        assert CombatService(ROOT,tmp_path).journey_replay(jid)['status']=='PASS'

def test_additional_sign_learning_uses_native_source_option_records(tmp_path):
    combat,table,mid=make(tmp_path,SKY,own=False)
    pid=OWNER.removeprefix('actor:factory.')
    table.add_advancement(pid,'sphere','tianxia.sphere.weather',choices={'weather_starting_sign':['cold']})
    for sign in ['rain','wind','heat','dry','thunder']:
        table.add_advancement(pid,'source_option','weather.sign.'+sign)
    document=CombatService(ROOT,tmp_path)._factory_owner_sheet(pid)
    bundle=compile_character(document,actor_id=OWNER)
    actions=[a for a in bundle['action_catalog'] if a.get('parameters',{}).get('typed',{}).get('source')=='WEATHER_BASE_CLOUD_SHROUD']
    assert actions and all(set(a['parameters']['typed']['known_weather_signs'])=={'wind','rain','cold','heat','dry','thunder'} for a in actions)

def test_weather_gm_concrete_object_damage_uses_native_object_rules(tmp_path):
    combat,table,mid=make(tmp_path,SKY,{'weather.vulnerable.heat':True,
        'weather.object_effect.heat':{'state':'Warped by heat','damage':{'amount':4,'type':'FIRE'}}},
        subject='object:map.601',objects=[{'id':601,'kind':'custom','material':'iron','x':4,'y':7,'hp':40,'blocks':False}])
    settle(table,mid,candidates(combat,mid,'WEATHER_BASE_CLOUD_SHROUD','object:map.601')[0].candidate_id,
        picks={'choice:needle.acquisition_weather_starting_sign':'heat','choice:needle.weather_shroud_sign':'heat'})
    obj=reload(tmp_path,mid).state.objects['object:map.601']
    assert obj.current_hp==36
    assert obj.component['weather_state']=='Warped by heat'
    assert 'Warped by heat' in json.dumps(table.state(mid)['objects'])

def test_hunger_common_predraw_cp_boost_is_optional_paid_and_replays(tmp_path):
    combat,table,mid=make(tmp_path,QI,{'qi.unwilling':True,'qi.concealing':True,'qi.defense':'CON','qi.fallback':'nourishing','qi.expression':'Cold qi'})
    settle(table,mid,candidates(combat,mid,QI,FOE)[0].candidate_id,picks={
        'choice:needle.reading_questions':'qi.expression','choice:needle.reading_hunger_steady':'3','choice:needle.fact_admission.qi_nature':'unwilling_concealed'})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources['resource:core.qi']==97
    roll=next(r for r in e.events if r.event_type=='CHECK_ROLLED' and r.actor_id==OWNER)
    assert roll.payload['actor']['modifier']==9  # PB 4 + key modifier 2 + 3 CP

def test_qi_human_defender_declaration_stays_player_owned_on_ai_reader_turn(tmp_path):
    combat,table,mid=make(tmp_path,QI,{'qi.defense':'CON','qi.fallback':'nourishing','qi.expression':'Cold qi'})
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    from tests.test_a2_daemonic import select_native_primary
    select_native_primary(combat,mid,'Taste the Qi',FOE)
    prompts=settle(table,mid,'',auto=True,picks={
        'choice:needle.reading_questions':'qi.expression','choice:needle.fact_admission.qi_nature':'unwilling_concealed'})
    declaration=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.fact_admission.qi_nature')
    assert declaration['context']['reactor_id']==FOE
    assert 'Mara' in json.dumps(declaration)
    e=reload(tmp_path,mid)
    assert any(r.event_type=='SAVE_ROLLED' and r.actor_id==FOE for r in e.events)

def test_profiles_pb_cap_and_free_owner_dismissal_on_another_turn(tmp_path):
    from combat.antidote_profiles import profiles
    objects=[{'id':601+i,'kind':'custom','material':'glass','x':4+i,'y':7,'blocks':False} for i in range(5)]
    inputs=[source('object:map.'+str(601+i),{'subject.kind':'sample','poison.present':True,'poison.kind':'Spiritual'}) for i in range(5)]
    combat,table,mid=make(tmp_path,VENOM,objects=objects,source_rows=inputs)
    for i in range(5):
        if i:
            settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
        settle(table,mid,candidates(combat,mid,VENOM,'object:map.'+str(601+i))[0].candidate_id,
            picks={'choice:needle.reading_questions':'poison.kind','choice:needle.reading_profile':'create',
                'choice:needle.antidote_profile_replace':'cancel'})
    e=reload(tmp_path,mid)
    assert len(profiles(e,e.state.actors[OWNER]))==4
    turn(table,mid,FOE)
    e=reload(tmp_path,mid)
    dismissal=next(a.source_definition_id for a in e.action_catalog.values() if a.owner_id==OWNER and a.parameters.get('antidote_profile_slot')==0)
    before=(e.state.current_actor_id,e.state.actors[OWNER].action_available,e.state.actors[OWNER].resources.copy())
    table.save_settings(mid,OWNER,[dismissal],'dismiss-profile-test')
    e=reload(tmp_path,mid)
    assert len(profiles(e,e.state.actors[OWNER]))==3
    assert (e.state.current_actor_id,e.state.actors[OWNER].action_available,e.state.actors[OWNER].resources)==before


def test_outside_antidote_profile_actual_long_rest_and_native_combat_transfer(tmp_path):
    from combat.antidote_profiles import profiles
    combat,table,mid=make(tmp_path,VENOM)
    state=journey(combat,{'poison.present':True,'poison.kind':'Spiritual'},ALLY);jid=state['journey_id']
    state=combat.journey_act(jid,0,OWNER,'information_reading',{'source':VENOM,'subject_id':ALLY,'questions':['poison.kind'],'profile':True})
    assert CombatService(ROOT,tmp_path).journey_replay(jid)['status']=='PASS'
    assert any(r['kind']=='declaration' for r in combat.journey_menu(jid,OWNER)['properties']['information'])
    state=combat.journey_act(jid,state['revision'],OWNER,'long_rest',{})
    assert state['seconds']==28800
    assert not [r for r in combat.journey_menu(jid,OWNER)['properties']['information'] if r['kind']=='declaration']
    assert CombatService(ROOT,tmp_path).journey_replay(jid)['status']=='PASS'
    state=combat.journey_act(jid,state['revision'],OWNER,'scene_turn',{'edge':'end'})
    state=combat.journey_act(jid,state['revision'],OWNER,'scene_turn',{'edge':'start'})
    state=combat.journey_act(jid,state['revision'],OWNER,'information_reading',{'source':VENOM,'subject_id':ALLY,'questions':['poison.kind'],'profile':True})
    result=combat.journey_start_combat(jid,state['revision'],{OWNER:'team:a',ALLY:'team:b'})
    fresh=CombatService(ROOT,tmp_path)._load_session(result['match_id'])
    assert fresh.mechanical.replay()['status']=='PASS'
    assert len(profiles(fresh.engine,fresh.engine.state.actors[OWNER]))==1


@pytest.mark.parametrize('distance,allowed',[(5,True),(30,False)])
def test_poison_touch_remains_legal_under_native_blindfold(tmp_path,distance,allowed):
    combat,table,mid=make(tmp_path,VENOM,{'poison.present':True,'poison.kind':'Spiritual'},
        position={'x':3+distance//5,'y':6},blind=True)
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,ALLY)
    e=combat._load_session(mid).engine
    cast=next(c for c in e.legal_candidates() if c.target_ids==(OWNER,) and
        e.action_catalog[c.source_definition_id].display_name=='Meld: Blindfold')
    settle(table,mid,cast.candidate_id)
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    e=reload(tmp_path,mid)
    assert any('blindfold' in c.source_definition_id for c in e.state.actors[OWNER].conditions.values())
    offered=candidates(combat,mid,VENOM,FOE)
    assert bool(offered)==allowed
    if allowed:
        settle(table,mid,offered[0].candidate_id,picks={'choice:needle.reading_questions':'poison.kind'})
        assert 'Spiritual' in json.dumps(answers(tmp_path,mid))


def test_weather_sign_gate_hides_unlearned_options_and_keeps_object_unknowns(tmp_path):
    combat,table,mid=make(tmp_path,SKY,objects=[{'id':601,'kind':'custom','material':'iron','x':4,'y':7,'blocks':False}])
    offered=candidates(combat,mid,'WEATHER_BASE_CLOUD_SHROUD','object:map.601')
    prompts=settle(table,mid,offered[0].candidate_id,picks={'choice:needle.acquisition_weather_starting_sign':'cold',
        'choice:needle.weather_shroud_sign':'cold'})
    sign=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.weather_shroud_sign')
    assert [o['id'] for o in sign['choice']['options']]==['cold']
    obj=reload(tmp_path,mid).state.objects['object:map.601']
    assert obj.component['cloud_shroud']['vulnerable']=='unknown'
    assert 'weather_state' not in obj.component


def test_private_answers_remain_hidden_after_expiry_in_history(tmp_path):
    combat,table,mid=make(tmp_path,QI,{'qi.expression':'Private frozen qi'})
    settle(table,mid,candidates(combat,mid,QI,FOE)[0].candidate_id,picks={'choice:needle.reading_questions':'qi.expression'})
    assert 'Private frozen qi' in json.dumps(answers(tmp_path,mid))
    for _ in range(2):
        settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    assert answers(tmp_path,mid)==[]
    assert 'Private frozen qi' not in json.dumps(table.events(mid,0))



def test_actual_native_death_remains_a_reachable_qi_corpse_without_consent(tmp_path):
    from combat.ext.life_state import is_deceased
    combat,table,mid=make(tmp_path,QI,{'qi.expression':'Lingering cold qi'},extra_foe=True,fragile_foe=True)
    for _ in range(6):
        e=reload(tmp_path,mid)
        if is_deceased(e.state.actors[FOE]):break
        attack=next(c for c in e.legal_candidates() if c.kind.value=='ATTACK' and c.target_ids==(FOE,))
        settle(table,mid,attack.candidate_id)
        settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    e=reload(tmp_path,mid);assert is_deceased(e.state.actors[FOE])
    offered=candidates(combat,mid,QI,FOE);assert offered
    prompts=settle(table,mid,offered[0].candidate_id,picks={'choice:needle.reading_questions':'qi.expression'})
    assert not any(p['context']['reaction_source_id']=='choice:needle.fact_admission.qi_nature' for p in prompts)
    assert 'Lingering cold qi' in json.dumps(answers(tmp_path,mid))


@pytest.mark.parametrize('row,talent,name,other',[
 (QI,'tianxia.talent.hunger.battle_ration','Battle Ration','tianxia.talent.hunger.clean_palate'),
 (METAL,'TAL_METAL_CONDUCTOR_S_PALM',"Conductor's Palm",'TAL_METAL_BELL_OF_SHATTERED_WEAPONS')])
def test_suitability_answers_only_name_actually_learned_talents(tmp_path,row,talent,name,other):
    key='qi.suitable' if row==QI else 'metal.suitable'
    values={'metal.bearing':True,key:{talent:True,other:True}}
    combat,table,mid=make(tmp_path,row,values,talent=talent)
    settle(table,mid,candidates(combat,mid,row,FOE)[0].candidate_id,picks={'choice:needle.reading_questions':key})
    result=json.dumps(answers(tmp_path,mid))
    assert name in result and other not in result and 'Yes' in result


def journey_settle(combat,jid,state,aid,kind,payload):
    state=combat.journey_act(jid,state['revision'],aid,kind,payload)
    for _ in range(16):
        pending=state.get('native_scene_pending')
        if not pending:return state
        owner=pending.get('awaiting_actor_id',aid)
        current=combat.journey_state(jid,viewer_id=owner)
        request=current['native_scene_pending']['request']
        spec=request.get('extension_choice') or {}
        options=list(spec.get('option_ids') or [])
        count=spec.get('minimum_selections',0)
        chosen=options[:count]
        answer={'selection':'USE' if chosen or not spec.get('allow_decline') else 'DECLINE','option_ids':chosen}
        state=combat.journey_act(jid,state['revision'],owner,'native_scene_answer',answer)
    raise AssertionError('Native scene choices did not terminate')


@pytest.mark.parametrize('sign',['wind','rain','cold','heat','dry','thunder'])
def test_outside_creature_shroud_uses_native_save_repeats_and_exact_elapsed_expiry(tmp_path,sign):
    from combat.ext.weather_shroud import SHROUD
    combat,table,mid=make(tmp_path,SKY,own=False)
    table.add_advancement(OWNER.removeprefix('actor:factory.'),'sphere','tianxia.sphere.weather',choices={'weather_starting_sign':[sign]})
    state=journey(combat,{'weather.air':True});jid=state['journey_id']
    action=next(r['payload'] for r in combat.journey_menu(jid,OWNER)['options'] if r['kind']=='native_scene_action' and r['payload']['subject_id']==ALLY)
    action={**action,'choices':{'choice:needle.weather_shroud_sign':[sign],'choice:needle.reading_battle_sign':[]}}
    state=journey_settle(combat,jid,state,OWNER,'native_scene_action',action)
    raw=combat.journeys.load(jid).state
    native=json.loads(raw['native_scene']['state'])
    assert any(c['condition_id']==SHROUD for c in native['actors'][ALLY]['conditions'].values())
    assert native['actors'][OWNER]['resources']['resource:core.qi']==99
    events=[json.loads(row) for row in raw['native_scene']['events']]
    first=sum(r['event_type']=='SAVE_ROLLED' and r['actor_id']==ALLY for r in events)
    assert first>=1
    state=journey_settle(combat,jid,state,ALLY,'scene_turn',{'edge':'start'})
    state=journey_settle(combat,jid,state,ALLY,'scene_turn',{'edge':'end'})
    events=[json.loads(row) for row in combat.journeys.load(jid).state['native_scene']['events']]
    assert sum(r['event_type']=='SAVE_ROLLED' and r['actor_id']==ALLY for r in events)>first
    assert CombatService(ROOT,tmp_path).journey_replay(jid)['status']=='PASS'
    state=combat.journey_act(jid,state['revision'],OWNER,'wait',{'seconds':59})
    native=json.loads(combat.journeys.load(jid).state['native_scene']['state'])
    assert any(c['condition_id']==SHROUD for c in native['actors'][ALLY]['conditions'].values())
    state=combat.journey_act(jid,state['revision'],OWNER,'wait',{'seconds':1})
    native=json.loads(combat.journeys.load(jid).state['native_scene']['state'])
    assert not any(c['condition_id']==SHROUD for c in native['actors'][ALLY]['conditions'].values())
    assert native['actors'][OWNER]['concentration'] is None
    assert CombatService(ROOT,tmp_path).journey_replay(jid)['status']=='PASS'


def test_outside_shroud_keeps_native_state_and_remaining_time_on_combat_entry(tmp_path):
    from combat.ext.weather_shroud import SHROUD
    combat,table,mid=make(tmp_path,SKY,own=False)
    table.add_advancement(OWNER.removeprefix('actor:factory.'),'sphere','tianxia.sphere.weather',choices={'weather_starting_sign':['cold']})
    state=journey(combat,{'weather.air':True});jid=state['journey_id']
    action=next(r['payload'] for r in combat.journey_menu(jid,OWNER)['options'] if r['kind']=='native_scene_action' and r['payload']['subject_id']==ALLY)
    state=journey_settle(combat,jid,state,OWNER,'native_scene_action',{**action,'choices':{'choice:needle.weather_shroud_sign':['cold'],'choice:needle.reading_battle_sign':[]}})
    state=combat.journey_act(jid,state['revision'],OWNER,'wait',{'seconds':30})
    native=json.loads(combat.journeys.load(jid).state['native_scene']['state'])
    hp=native['actors'][ALLY]['current_hp']
    result=combat.journey_start_combat(jid,state['revision'],{OWNER:'team:a',ALLY:'team:b'})
    e=reload(tmp_path,result['match_id'])
    assert e.state.actors[ALLY].current_hp==hp and e.state.actors[OWNER].resources['resource:core.qi']==99
    shroud=next(c for c in e.state.actors[ALLY].conditions.values() if c.condition_id==SHROUD)
    assert shroud.data['expiry_round']==6
    assert e.state.actors[OWNER].concentration is not None


def test_read_vessel_derives_active_mandate_and_speed_from_an_actual_self_imbue(tmp_path):
    combat,table,mid=make(tmp_path,VESSEL,{'vessel.dc':0,'vessel.mandate':False},subject=OWNER,
        talent='tianxia.talent.imbuement.quicken_and_slow')
    e=combat._load_session(mid).engine
    cast=next(c for c in e.legal_candidates() if c.target_ids==(OWNER,) and
        (a:=e.action_catalog.get(c.source_definition_id)) is not None and a.display_name=='Place Mandate: Quicken')
    settle(table,mid,cast.candidate_id)
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    settle(table,mid,candidates(combat,mid,VESSEL,OWNER)[0].candidate_id,
        picks={'choice:needle.reading_questions':['vessel.mandate','vessel.enhancement']})
    result=answers(tmp_path,mid)[-1]['details']['answers']
    assert result['Currently affected by a Mandate?']=='Yes'
    assert 'speed' in result['Active creature enhancement']


def test_native_scene_rejects_unowned_cast_and_other_controller_answer(tmp_path):
    combat,table,mid=make(tmp_path,SKY,own=False)
    with pytest.raises(ValueError,match='native scene turn'):
        combat._load_session(mid).engine.scene_turn(OWNER,'start',1)
    state=journey(combat,{'weather.air':True});jid=state['journey_id']
    with pytest.raises(ValueError,match='not enabled'):
        combat.journey_act(jid,state['revision'],ALLY,'native_scene_action',{'action_id':'forged','subject_id':OWNER})
    assert combat.journey_replay(jid)['status']=='PASS'
    assert 'native_scene' not in combat.journeys.load(jid).state
    state=combat.journey_act(jid,state['revision'],OWNER,'finish',{})
    table.add_advancement(OWNER.removeprefix('actor:factory.'),'sphere','tianxia.sphere.weather')
    state=journey(combat,{'weather.air':True});jid=state['journey_id']
    action=next(r['payload'] for r in combat.journey_menu(jid,OWNER)['options'] if r['kind']=='native_scene_action' and r['payload']['subject_id']==ALLY)
    state=combat.journey_act(jid,state['revision'],OWNER,'native_scene_action',action)
    request=state['native_scene_pending']['request']
    selected=list(request['extension_choice']['option_ids'])[:1]
    with pytest.raises(ValueError,match='Only this choice'):
        combat.journey_act(jid,state['revision'],ALLY,'native_scene_answer',{'selection':'USE','option_ids':selected})
    assert combat.journeys.load(jid).state['actors'][OWNER]['resources']['resource:core.qi']==100
    state=journey_settle(combat,jid,state,OWNER,'native_scene_answer',{'selection':'USE','option_ids':selected})
    assert 'native_scene_pending' not in state and combat.journey_replay(jid)['status']=='PASS'


def test_outside_object_shroud_commits_physical_damage_and_ends_concentration_freely(tmp_path):
    combat,table,mid=make(tmp_path,SKY,own=False)
    table.add_advancement(OWNER.removeprefix('actor:factory.'),'sphere','tianxia.sphere.weather',choices={'weather_starting_sign':['heat']})
    from copy import deepcopy
    arena=deepcopy(combat.factory_arenas()['battlefield:map.builtin-sect-trial-platform'])
    arena['map_objects']=[{'id':601,'kind':'custom','material':'wood','x':5,'y':5,'blocks':False,'hp':20}]
    from combat.encounter_sources import prepare
    from combat.journey import JourneyStore
    bundles=[compile_character(combat._factory_owner_sheet(a.removeprefix('actor:factory.')),actor_id=a) for a in (OWNER,ALLY)]
    arena=prepare(arena,[source('object:map.601',{'weather.vulnerable.heat':True,'weather.object_effect.heat':{'damage':{'amount':3,'type':'FIRE'},'state':'warped'}})],[OWNER,ALLY])
    state=combat.journeys.create(bundles,arena,{OWNER:{'x':4,'y':5},ALLY:{'x':4,'y':6}},{OWNER:5,ALLY:5});jid=state['journey_id']
    action=next(r['payload'] for r in combat.journey_menu(jid,OWNER)['options'] if r['kind']=='native_scene_action' and r['payload']['subject_id']=='object:map.601')
    state=journey_settle(combat,jid,state,OWNER,'native_scene_action',{**action,'choices':{'choice:needle.weather_shroud_sign':['heat'],'choice:needle.reading_battle_sign':[]}})
    raw=combat.journeys.load(jid).state;obj=raw['runtime_objects']['object:map.601']
    assert obj['component']['weather_state']=='warped' and obj['current_hp']<obj['maximum_hp']
    ending=next(r['payload'] for r in combat.journey_menu(jid,OWNER)['options'] if r['kind']=='native_scene_end_concentration')
    state=combat.journey_act(jid,state['revision'],OWNER,'native_scene_end_concentration',ending)
    obj=combat.journeys.load(jid).state['runtime_objects']['object:map.601']
    assert 'cloud_shroud' not in obj['component'] and obj['component']['weather_state']=='warped'
    assert CombatService(ROOT,tmp_path).journey_replay(jid)['status']=='PASS'


def test_table_owner_world_input_is_native_idempotent_private_and_replayed(tmp_path):
    from combat.encounter_sources import payload as fact_payload
    combat,table,mid=make(tmp_path,QI)
    engine=reload(tmp_path,mid);before=engine.state.actors[OWNER].resources.copy()
    body=fact_payload(FOE,'qi.expression',{'value':'A newly declared frozen presence'})
    result=table.world_fact(mid,engine.state.state_version,'known-qi-1',body)
    assert table.world_fact(mid,engine.state.state_version,'known-qi-1',body)==result
    with pytest.raises(Exception,match='different source input'):
        table.world_fact(mid,result['state_version'],'known-qi-1',fact_payload(FOE,'qi.expression',{'value':'different'}))
    settle(table,mid,candidates(combat,mid,QI,FOE)[0].candidate_id,picks={'choice:needle.reading_questions':'qi.expression'})
    assert 'A newly declared frozen presence' in json.dumps(answers(tmp_path,mid))
    e=reload(tmp_path,mid);assert e.state.actors[OWNER].resources==before
    assert 'A newly declared frozen presence' not in json.dumps(table.events(mid,0))
    assert sum(r.event_type=='WORLD_FACT_DECLARED' for r in e.events)==1
    with pytest.raises(Exception,match='cannot supply'):
        table.world_fact(mid,e.state.state_version,'no-gm-consent',{'source':QI,'subject':FOE,'kind':'qi_nature','scope':'scene',
            'value':'open','expires_at':6,'readers':[OWNER]})
    assert reload(tmp_path,mid).state.state_version==e.state.state_version


@pytest.mark.parametrize('row,question,values,pack',[
 (QI,'qi.expression',{'subject.kind':'container','qi.expression':'Cold pressure'},True),
 (TRACE,'trace.age',{'trace.present':True,'trace.age':'An old inscription'},False),
 (VESSEL,['vessel.safe','vessel.nature'],{'vessel.dc':0,'vessel.safe':'Light','vessel.nature':'Spiritual'},False),
 (VENOM,'poison.kind',{'poison.present':True,'poison.kind':'Spiritual'},False),
 (METAL,'metal.material',{'metal.bearing':True,'metal.material':'Bronze'},False)])
def test_native_inventory_acquisition_scoped_appraisal_does_not_reveal_item_owner(tmp_path,row,question,values,pack):
    from tests.test_carry import KIT
    def inputs(bundles):
        inventory=bundles[2]['carrying']['items']
        item=next(r for r in inventory if ('pack' in r['item_id'] if pack else r.get('weapon_action')))
        return [{**source(FOE,{'item.visible':True,'item.touchable':True,**values}),'scope':'item:'+item['key']}]
    combat,table,mid=make(tmp_path,row,kit={'starting_kit':KIT},source_rows=inputs)
    offered=candidates(combat,mid,row,OWNER,suffix='carried or dropped item');assert offered
    prompts=settle(table,mid,offered[0].candidate_id,picks={'choice:needle.reading_questions':question})
    item_choice=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.reading_inventory')
    assert len(item_choice['choice']['options'])==1
    result=json.dumps(answers(tmp_path,mid))
    expected=values[question[0] if isinstance(question,list) else question]
    assert expected in result and FOE not in result and 'Mara' not in result
    assert result not in json.dumps(table.events(mid,0))
    assert not any(p['context']['reaction_source_id']=='choice:needle.fact_admission.qi_nature' for p in prompts)


def test_outside_vessel_inventory_one_minute_native_procedure_has_no_turn_cost(tmp_path):
    from tests.test_carry import KIT
    combat,table,mid=make(tmp_path,VESSEL,kit={'starting_kit':KIT})
    state=journey(combat,{},ALLY);jid=state['journey_id']
    bundle=compile_character(combat._factory_owner_sheet(ALLY.removeprefix('actor:factory.')),actor_id=ALLY)
    item=next(r for r in bundle['carrying']['items'] if r.get('weapon_action'))
    from combat.encounter_sources import payload
    for key,value in {'item.visible':True,'item.touchable':True,'vessel.dc':0,'vessel.safe':'Light','vessel.nature':'Spiritual'}.items():
        state=combat.journey_world_fact(jid,state['revision'],payload(ALLY,key,{'value':value},'item:'+item['key']))
    menu=combat.journey_menu(jid,OWNER)
    option=next(r for r in menu['options'] if r['kind']=='native_scene_procedure' and '#inventory' in r['payload']['action_id'] and '#internal' not in r['payload']['action_id'])
    chosen={**option['payload'],'choices':{'choice:needle.reading_questions':['vessel.safe','vessel.nature'],'choice:needle.reading_check':['INT:Arcana']}}
    state=combat.journey_act(jid,state['revision'],OWNER,'native_scene_procedure',chosen)
    assert state['seconds']==60 and 'source_turn' not in state['actors'][OWNER]
    result=combat.journey_menu(jid,OWNER)['properties']['information']
    assert 'Light' in json.dumps(result) and ALLY not in json.dumps(result)
    assert CombatService(ROOT,tmp_path).journey_replay(jid)['status']=='PASS'
