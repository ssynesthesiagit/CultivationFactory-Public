"""Mantis native acquisition, table commits, cold replay guards."""
import json
import zipfile
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, candidate, settle, reload, turn

PARENT='tianxia.subpath.body.mantis_style'
P=PARENT+'.feature.'
STAMINA='resource:core.stamina'


def native(tmp_path,cl=18):
    for aid,owner in ((OWNER,True),(ALLY,False),(FOE,False)):
        doc=sheet([],cl=cl,primary='Stamina' if owner else 'Qi',score=30 if owner else 10,
                  name='Mantis practitioner' if owner else 'Defender')
        if owner:doc['identity']['path']='Body Refining'
        stats=doc['ability_scores_and_statistics']
        stats['primary_resource']['maximum']=100
        stats['hit_points']['maximum']=1000
        stats['armor_class']['base_value']=5
        folder=tmp_path/'portable_characters'/aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    combat=CombatService(ROOT,tmp_path)
    journey=combat.create_journey(project_ids=['worker2-owner','worker2-ally','worker2-foe'],
        arena_id='battlefield:factory_pillar_arena',positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':4,'y':6}},
        base_paces={OWNER:3000,ALLY:3000,FOE:3000})
    acquired=combat.journey_acquire_source(journey['journey_id'],journey['revision'],OWNER,PARENT,{'operation':'select'})
    result=combat.journey_start_combat(journey['journey_id'],acquired['revision'],
        {OWNER:'team:factory',ALLY:'team:opponents',FOE:'team:opponents'})
    table=TabletopService(combat,tmp_path);mid=result['match_id']
    turn(table,mid,OWNER)
    return combat,table,mid


def strike(combat,mid,pincer=False):
    e=combat._load_session(mid).engine
    return next(c for c in e.legal_candidates() if c.target_ids==(FOE,)
        and '.natural.' in c.source_definition_id
        and bool(e.action_catalog[c.source_definition_id].parameters.get('rapid_pincer'))==pincer)


def test_acquisition_derives_all_five_from_installed_body_progression(tmp_path):
    combat,table,mid=native(tmp_path)
    e=reload(tmp_path,mid)
    assert len([r for r in e.typed_passive_rows[OWNER] if str(r.get('feature_id','')).startswith(P)])>=3
    assert candidate(combat,mid,'Eye of the Mantis',target=FOE)
    assert not any('Mantis' in e.action_catalog[a].display_name for a in e.state.actors[FOE].action_ids)


def test_hooks_light_precedes_all_damage_dice_and_uses_target_choice(tmp_path):
    combat,table,mid=native(tmp_path)
    prompts=settle(table,mid,strike(combat,mid).candidate_id,picks={
        'choice:needle.mantis_hooks_light':'light','choice:needle.mantis_hooks':'grapple',
        'choice:needle.save_choice':'STR',
        'choice:needle.path_hit.'+P+'death_of_a_thousand_cuts':None})
    e=reload(tmp_path,mid)
    rolls=[r for r in e.rolls if r.reason.startswith('DAMAGE:') and r.actor_id==OWNER]
    assert rolls and not rolls[-1].dice
    assert e.state.actors[FOE].current_hp==990
    hold=next(c for c in e.state.actors[FOE].conditions.values() if c.condition_id.endswith('.grappled'))
    assert hold.source_actor_id==OWNER and hold.data['grappling_part'].startswith('hand:')
    saves=[r for r in e.rolls if r.reason.startswith('SAVE:') and r.actor_id==FOE]
    assert saves[-1].reason.endswith(':STR') and saves[-1].mode=='DISADVANTAGE'
    assert any(p['context']['reactor_id']==FOE for p in prompts)
