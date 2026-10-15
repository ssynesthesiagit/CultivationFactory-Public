"""Native Open School acquisition -> journey -> table commit -> cold replay."""
import json
import zipfile
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.factory_compiler import compile_character
from tests.h1_support import ROOT,sheet
from tests.worker2_support import settle,turn,candidate,reload
PARENT='tianxia.subpath.qi.lantern_keeper'
P=PARENT+'.feature.'
OWNER='actor:factory.lantern-keeper'
ALLY='actor:factory.traveler'
FOE='actor:factory.raider'
ALL=[P+s for s in ('light_the_way','lantern_road','lantern_passage','hold_the_departing_soul','ten_thousand_lantern_road')]
POS={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':7,'y':6}}

def journey(tmp_path,cl=18,*,foe_ids=(),ally_hp=60,owner_ids=()):
    docs=[sheet(owner_ids,cl=cl,name='Wren'),sheet([],cl=cl,name='Tobin'),sheet(foe_ids,cl=cl,name='Mara')]
    docs[0]['path_and_subpath']={**docs[0].get('path_and_subpath',{}),'path_record_ids':['tianxia.path.qi_cultivation'],
        'paths':[{'path_id':'tianxia.path.qi_cultivation','attainment':cl}]}
    docs[1]['ability_scores_and_statistics']['hit_points']['maximum']=ally_hp
    for aid,doc in zip(POS,docs):
        doc['ability_scores_and_statistics']['primary_resource']['maximum']=100
        folder=tmp_path/'portable_characters'/aid.removeprefix('actor:factory.');folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    combat=CombatService(ROOT,tmp_path)
    s=combat.create_journey(project_ids=[a.removeprefix('actor:factory.') for a in POS],arena_id='battlefield:factory_pillar_arena',
        positions=POS,base_paces={a:1000 for a in POS},control_modes={a:'MANUAL' for a in POS})
    return combat,s

def play(tmp_path,cl=18,**kw):
    combat,s=journey(tmp_path,cl,**kw)
    s=combat.journey_acquire_source(s['journey_id'],s['revision'],OWNER,PARENT,{})
    mid=combat.journey_start_combat(s['journey_id'],s['revision'],{OWNER:'team:guides',ALLY:'team:guides',FOE:'team:raiders'},positions=POS,maximum_rounds=50)['match_id']
    table=TabletopService(combat,tmp_path);turn(table,mid,OWNER)
    return combat,table,mid

def cast(combat,table,mid,name,picks=None):
    return settle(table,mid,candidate(combat,mid,name).candidate_id,picks=picks or {})

def lamps(engine):
    return [o for o in engine.state.objects.values() if not o.destroyed and o.object_kind=='guiding_lantern']

def create(combat,table,mid,point='cell:3:6:0'):
    return cast(combat,table,mid,'Create Guiding Lantern',{'choice:needle.lantern_lantern_form':'projected','choice:needle.lantern_lantern_location':point})

def test_acquisition_is_native_exclusive_persisted_and_default_inert(tmp_path):
    combat,s=journey(tmp_path);jid=s['journey_id']
    assert not any(r.get('block')=='lantern_keeper' for r in s['actors'][OWNER]['bundle']['typed_passives'])
    before=combat.journey_state(jid)
    with pytest.raises(ValueError):combat.journey_acquire_source(jid,s['revision'],ALLY,PARENT,{})
    assert combat.journey_state(jid)==before
    s=combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})
    assert {r['feature_id'] for r in s['actors'][OWNER]['bundle']['typed_passives'] if r.get('block')=='lantern_keeper'}==set(ALL)
    assert any(e['kind']=='LANTERN_KEEPER_ACQUIRED' for e in s['events'])
    assert CombatService(ROOT,tmp_path).journey_state(jid)==s
    with pytest.raises(ValueError):combat.journey_acquire_source(jid,s['revision'],OWNER,PARENT,{})

@pytest.mark.parametrize('cl,count',[(2,0),(3,1),(5,1),(6,2),(9,2),(10,3),(13,3),(14,4),(17,4),(18,5)])
def test_progression_thresholds(cl,count):
    b=compile_character(sheet(ALL,cl=cl),actor_id=OWNER)
    assert len([r for r in b['typed_passives'] if r.get('block')=='lantern_keeper'])==count

def test_create_paid_native_profile_no_space_and_cold_replay(tmp_path):
    combat,table,mid=play(tmp_path);prompts=create(combat,table,mid)
    e=reload(tmp_path,mid);a=e.state.actors[OWNER]
    assert len(lamps(e))==1
    o=lamps(e)[0]
    assert (o.ac,o.current_hp,o.maximum_hp)==(17,36,36)
    assert set(o.damage_immunities)=={'FIRE','POISON','PSYCHIC'} and o.position==a.position
    assert a.resources['resource:core.qi']==99 and not a.action_available
    assert o.component['hover'] and o.component['speed_ft']==20
    assert not o.component['blocks'] and not o.component['creature'] and not o.component['cover']
    assert prompts
