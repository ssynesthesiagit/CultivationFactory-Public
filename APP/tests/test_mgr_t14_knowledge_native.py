"""Native learning -> authoritative source input -> table -> cold reload/replay."""
import json, zipfile
import pytest
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT,sheet
from tests.worker2_support import OWNER,ALLY,FOE,settle,turn,reload

QI='HUNGER_BASE_TASTE_THE_QI';TRACE='INK_BASE_READ_THE_TRACE';VESSEL='IMBUEMENT_BASE_READ_THE_VESSEL'
VENOM='POISON_BASE_APPRAISE_THE_VENOM';METAL='METAL_BASE_METAL_APPRAISAL';SKY='WEATHER_BASE_READ_THE_SKY'
SPHERES={QI:'hunger',TRACE:'ink',VESSEL:'imbuement',VENOM:'poison',METAL:'metal',SKY:'weather'}

def source(subject,values):
    return {'subject_id':subject,'authority_actor_id':OWNER,'authority_role':'gm','facts':{k:{'value':v} for k,v in values.items()}}

def make(tmp_path,row,values=None,*,subject=FOE,own=True,position=None,objects=None):
    for aid in (OWNER,ALLY,FOE):
        doc=sheet([],cl=15,name={OWNER:'Wren',ALLY:'Tobin',FOE:'Mara'}[aid])
        doc['identity']['path_ids']=['tianxia.path.qi_cultivation']
        doc['path_and_subpath']={'path_record_id':'tianxia.path.qi_cultivation','path_record_ids':['tianxia.path.qi_cultivation']}
        doc['ability_scores_and_statistics']['primary_resource']['maximum']=100
        folder=tmp_path/'portable_characters'/aid.removeprefix('actor:factory.');folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    combat=CombatService(ROOT,tmp_path);table=TabletopService(combat,tmp_path)
    table.canonical_catalog=CanonicalCatalogAuthorityService(ROOT)
    if own:table.add_advancement(OWNER.removeprefix('actor:factory.'),'sphere','tianxia.sphere.'+SPHERES[row])
    bundles=[compile_character(combat._factory_owner_sheet(a.removeprefix('actor:factory.')),actor_id=a,reaction_plan={'ask':True}) for a in (OWNER,ALLY,FOE)]
    from copy import deepcopy
    arena=deepcopy(combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'])
    if objects:arena['map_objects']=objects
    mid=combat._finish_factory_match(bundles,[OWNER,ALLY,FOE],{OWNER:'team:factory',ALLY:'team:factory',FOE:'team:opponents'},
        {OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:position or {'x':4,'y':6}},arena,[OWNER,ALLY],[FOE],
        control_modes={a:'MANUAL' for a in (OWNER,ALLY,FOE)},match_seed='KNOWLEDGE',display_name='Knowledge',maximum_rounds=15,
        source_inputs=[source(subject,values)] if values else None)['match_id']
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
    with pytest.raises(ValueError,match='unauthorized'):
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
 (QI,'ingredient','qi.impurity',True),(TRACE,'inscription','trace.age','Written recently'),
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
