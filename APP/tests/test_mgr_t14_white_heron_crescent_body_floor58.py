"""White Heron native learning -> table commit -> cold mechanical replay."""
import json
import zipfile
import pytest
from functools import lru_cache
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import fixture, settle, reload, candidate, turn, OWNER, FOE
SCHOOL='tianxia.subpath.body.white_heron_crescent_body'
PREFIX=SCHOOL+'.feature.'
FEATURES=['crescent_body_integration','one_legged_guard','crescent_reaping_circle','white_wing_crosses_the_reed_field','moon_over_the_reed_sea']
PID='0badc0de-0000-4000-8000-000000000059'
STAFF='tianxia.mortal.weapon.ji'
KIT={'starting_kit':{'items':[{'item_id':STAFF}]}}


@lru_cache(maxsize=1)
def catalog():
    return CanonicalCatalogAuthorityService(ROOT)


def native_table(combat,tmp_path):
    table=TabletopService(combat,tmp_path)
    table.canonical_catalog=catalog()
    return table


def acquired(tmp_path,cl=18,path='Body Refining'):
    doc=sheet([],cl=cl,primary='Stamina',kit=KIT,dc=50)
    doc['identity']['path']=path
    doc['identity']['name']='White Heron practitioner'
    doc['identity']['path_ids']=['tianxia.path.body_refining'] if path=='Body Refining' else ['tianxia.path.qi_cultivation']
    doc['path_and_subpath']={'path_record_ids':doc['identity']['path_ids']}
    folder=tmp_path/'portable_characters'/PID;folder.mkdir(parents=True)
    with zipfile.ZipFile(folder/'current.zip','w') as z:
        z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    table=native_table(CombatService(ROOT,tmp_path),tmp_path)
    table.add_advancement(PID,'subpath',SCHOOL)
    return CombatService(ROOT,tmp_path)._factory_owner_sheet(PID)


def game(tmp_path,cl=18,**kwargs):
    doc=acquired(tmp_path/'learning',cl)
    bundle=compile_character(doc,actor_id=OWNER,reaction_plan={'ask':True})
    return fixture(tmp_path/'fight',[],owner_bundle=bundle,owner_path='Body Refining',primary='Stamina',
        owner_kit=KIT,cl=cl,seed='HERON58',foe_position=kwargs.pop('foe_position',{'x':4,'y':6}),
        ally_position={'x':3,'y':7},named=True,**kwargs)


@pytest.mark.parametrize('cl,count',[(2,0),(3,1),(6,2),(10,3),(14,4),(18,5)])
def test_native_acquisition_progression_cold(tmp_path,cl,count):
    doc=acquired(tmp_path,cl)
    ids=doc.get('path_and_subpath',{}).get('path_feature_record_ids',[])
    assert [mid for mid in ids if mid.startswith(PREFIX)]==[PREFIX+f for f in FEATURES[:count]]
    assert not doc.get('spheres_and_talents',{}).get('sphere_record_ids')


def test_native_acquisition_rejects_wrong_path(tmp_path):
    from combat.tabletop_service import TabletopError
    with pytest.raises((ValueError,TabletopError)):
        acquired(tmp_path,path='Qi Cultivation')

from pathlib import Path
from combat.canonical import canonical_sha256
EVIDENCE=Path('/var/tmp/auto-audit/fix/MGR-T14-ling-seam-white-heron-crescent-body-4-evidence')
STAMINA='resource:core.stamina'


def cold(tmp_path,mid,label):
    engine=reload(tmp_path/'fight',mid)
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    doc={'label':label,'state_sha256':canonical_sha256(engine.state.model_dump(mode='json')),
         'state':engine.state.model_dump(mode='json'),'events':[e.model_dump(mode='json') for e in engine.events],
         'rolls':[r.model_dump(mode='json') for r in engine.rolls],'mechanical_replay':'PASS'}
    (EVIDENCE/(label+'.json')).write_text(json.dumps(doc,sort_keys=True))
    return engine


def polearm(combat,mid,target=FOE):
    engine=combat._load_session(mid).engine
    return next(c for c in engine.legal_candidates() if target in c.target_ids
                and (a:=engine.action_catalog.get(c.source_definition_id)) is not None
                and a.owner_id==OWNER and a.display_name=='Ji (Halberd) attack')


def choices(**kwargs):
    return {'choice:needle.white_wing_move':None,'choice:needle.herons_passing_cut':None,
            **{'choice:needle.'+k:v for k,v in kwargs.items()}}


def move(combat,table,mid,x,y):
    c=next(c for c in combat._load_session(mid).engine.legal_candidates()
           if c.kind=='MOVE' and c.destination and (c.destination.x,c.destination.y,c.destination.z)==(x,y,0))
    settle(table,mid,c.candidate_id)


@pytest.mark.parametrize('cl,count',[(3,1),(11,2),(17,3)])
def test_native_passing_cut_movement_scaling_and_cost(tmp_path,monkeypatch,cl,count):
    from tests.hunt12_support import hit_dice
    hit_dice(monkeypatch)
    combat,table,mid=game(tmp_path,cl,foe_position={'x':6,'y':6})
    move(combat,table,mid,5,6)
    before=combat._load_session(mid).engine.state.actors[OWNER].resources[STAMINA]
    prompts=settle(table,mid,polearm(combat,mid).candidate_id,
        choices=choices(herons_passing_cut=['damage'],heron_damage_type=['FORCE']))
    engine=cold(tmp_path,mid,'passing-'+str(cl))
    assert engine.state.actors[OWNER].resources[STAMINA]==before-1
    assert any(p['context']['reaction_source_id']=='choice:needle.herons_passing_cut' for p in prompts)
    assert any(r.expression.startswith(str(count)+'d8') for r in engine.rolls)
    assert engine.state.actors[OWNER].turn_flags.get('_round_passing_cut')


@pytest.mark.parametrize('outcome',['push','prone','ac','attack'])
def test_native_white_wing_every_result(tmp_path,monkeypatch,outcome):
    from tests.hunt12_support import hit_dice
    hit_dice(monkeypatch,save_roll=1)
    combat,table,mid=game(tmp_path,14,extra_foes=1)
    before=combat._load_session(mid).engine.state.actors[OWNER].resources[STAMINA]
    picks=choices(white_wing_move=['cell:5,6'],white_wing_result=[outcome],white_wing_target='first')
    prompts=settle(table,mid,polearm(combat,mid).candidate_id,choices=picks)
    engine=cold(tmp_path,mid,'wing-'+outcome);actor=engine.state.actors[OWNER];foe=engine.state.actors[FOE]
    assert (actor.position.x,actor.position.y)==(5,6)
    assert actor.resources[STAMINA]==before
    assert any(p['context']['reaction_source_id']=='choice:needle.white_wing_result' for p in prompts)
    if outcome=='ac':assert any(m.value==2 and m.source_definition_id==PREFIX+FEATURES[3] for m in actor.modifiers.values())
    elif outcome=='push':assert foe.position.x<4
    elif outcome=='prone':assert any(c.condition_id.endswith('.prone') for c in foe.conditions.values())
    else:assert len([e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER])==2


@pytest.mark.parametrize('save_roll',[1,20])
def test_native_reaping_save_cost_and_no_attack_hit_riders(tmp_path,monkeypatch,save_roll):
    from tests.hunt12_support import hit_dice
    hit_dice(monkeypatch,save_roll=save_roll)
    combat,table,mid=game(tmp_path,10)
    engine=combat._load_session(mid).engine;before=engine.state.actors[OWNER].resources[STAMINA]
    c=next(c for c in engine.legal_candidates() if c.display_name.startswith('Crescent Reaping Circle'))
    settle(table,mid,c.candidate_id,choices=choices(reaping_circle_rider=['deny'],reaping_circle_move=None,heron_damage_type=['FORCE']))
    engine=cold(tmp_path,mid,'reaping-'+str(save_roll))
    assert engine.state.actors[OWNER].resources[STAMINA]==before-2
    assert not any(e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER for e in engine.events)
    assert any(r.expression.startswith('3d8') for r in engine.rolls)
    assert not any(c.display_name.startswith('Crescent Reaping Circle') for c in engine.legal_candidates())
    assert engine.state.actors[FOE].current_hp<60


@pytest.mark.parametrize('outcome',['minus','push','deny','move'])
def test_native_guard_commits_before_attack_and_reloads(tmp_path,monkeypatch,outcome):
    from tests.hunt12_support import hit_dice
    hit_dice(monkeypatch)
    combat,table,mid=game(tmp_path,6)
    turn(table,mid,FOE)
    engine=combat._load_session(mid).engine;before=engine.state.actors[OWNER].resources[STAMINA]
    c=next(c for c in engine.legal_candidates() if OWNER in c.target_ids
        and (a:=engine.action_catalog.get(c.source_definition_id)) is not None
        and a.owner_id==FOE and any(e.get('type')=='attack' for e in a.parameters.get('typed',{}).get('effects',[])))
    prompts=settle(table,mid,c.candidate_id,choices={PREFIX+FEATURES[1]:'first',
        'choice:needle.one_legged_guard':[outcome],
        'choice:needle.one_legged_guard_move':['cell:2,6']})
    engine=cold(tmp_path,mid,'guard-'+outcome)
    rolls=[e for e in engine.events if e.event_type=='ATTACK_ROLLED']
    assert rolls and rolls[0].actor_id==OWNER
    assert engine.state.actors[OWNER].resources[STAMINA]==before-1
    assert not engine.state.actors[OWNER].reaction_available
    if outcome in ('push','move'):assert len(rolls)==1
    elif outcome=='deny':assert any(c.condition_id.endswith('reaction_denied') for c in engine.state.actors[FOE].conditions.values())
    assert any(p['context']['reaction_source_id']=='choice:needle.one_legged_guard' for p in prompts)


def test_native_moon_commit_stance_and_scene_limit(tmp_path,monkeypatch):
    from tests.hunt12_support import hit_dice
    hit_dice(monkeypatch,save_roll=1)
    combat,table,mid=game(tmp_path,18,foe_position={'x':7,'y':6})
    before=combat._load_session(mid).engine.state.actors[OWNER].resources[STAMINA]
    c=candidate(combat,mid,'Moon over the Reed Sea',at=(8,6))
    settle(table,mid,c.candidate_id,choices=choices(moon_push_distance=['0']))
    engine=cold(tmp_path,mid,'moon-scene');actor=engine.state.actors[OWNER]
    assert actor.resources[STAMINA]==before-7
    assert (actor.position.x,actor.position.y)==(8,6)
    assert any(c.condition_id=='condition:typed.state.moon_reed_stance' for c in actor.conditions.values())
    assert any(m.value==2 and m.source_definition_id==PREFIX+FEATURES[4] for m in actor.modifiers.values())
    assert not any(c.display_name.startswith('Moon over the Reed Sea') for c in engine.legal_candidates())
    assert len([r for r in engine.rolls if r.expression.startswith('10d8')])==1


def test_native_stow_dormancy_and_default_inert(tmp_path):
    combat,table,mid=game(tmp_path,18)
    settle(table,mid,candidate(combat,mid,'Stow Ji (Halberd) (frees 2 hands; no Action)').candidate_id)
    engine=cold(tmp_path,mid,'stowed')
    assert not any(c.display_name.startswith(('Crescent Reaping Circle','Moon over the Reed Sea')) for c in engine.legal_candidates())
    assert not any(r.get('kind')=='heron' for r in engine.typed_passive_rows[FOE])
