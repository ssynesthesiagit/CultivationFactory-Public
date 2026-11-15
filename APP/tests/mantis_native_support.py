"""Synthetic native Mantis table fixture shared by Mantis and damage tests."""
import json
import zipfile
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, candidate, reload, turn

PARENT='tianxia.subpath.body.mantis_style'
P=PARENT+'.feature.'
STAMINA='resource:core.stamina'



def settle(table,mid,cid,picks=None,*,auto=False):
    """Drive all distinct real choices; a repeated checkpoint is a hard failure.

    A CL18 Attack action has four strikes (five with Rapid Pincer) and may
    legally ask more than twenty choices. This does not alter a production
    limit or the shared fixture helper; every response uses the native API.
    """
    from tests.table_act_support import act
    answers=[];prompts=[];seen=set();counts={};picks=picks or {}
    while True:
        result=table.auto_step(mid,0,answers) if auto else act(table,mid,cid,answers)
        if result['status']!='REACTION_REQUIRED':
            assert result['status']=='COMMITTED',result
            return prompts
        prompt=result['reaction'];context=prompt['context'];rid=context['reaction_source_id']
        identity=(context['checkpoint'],context['reactor_id'],rid)
        assert identity not in seen,('Native choice repeated without progress',identity)
        seen.add(identity);prompts.append(prompt)
        chosen=picks.get(rid,None if rid=='choice:needle.mantis_pincer_use' else 'first' if rid.startswith('choice:') else None)
        count=counts.get(rid,0);counts[rid]=count+1
        if isinstance(chosen,tuple):chosen=chosen[min(count,len(chosen)-1)]
        answer={**context,'selection':'USE' if chosen is not None else 'DECLINE'}
        if chosen is not None and prompt.get('choice'):
            answer['option_ids']=([prompt['choice']['options'][0]['id']] if chosen=='first'
                else chosen if isinstance(chosen,list) else [chosen])
        answers.append(answer)


def native(tmp_path,cl=18,foe_kit=None,before_acquire=None,before_combat=None,control_modes=None,foe_saves=None,foe_body=False,friendly_ally=False,maximum_rounds=20,foe_talents=(),ally_talents=(),foe_size=None,foe_position=None,owner_stamina=100,owner_con_score=None,advance_owner=True,owner_str_score=None,foe_hp=1000):
    for aid,owner in ((OWNER,True),(ALLY,False),(FOE,False)):
        doc=sheet(list(foe_talents) if aid==FOE else list(ally_talents) if aid==ALLY else [],cl=cl,primary='Stamina' if owner else 'Qi',score=30 if owner else 10,dc=100 if owner else 16,kit=foe_kit if aid==FOE else None,
                  name='Mantis practitioner' if owner else 'Defender')
        if owner:
            doc['identity']['path']='Body Refining'
            # The installed starting build has its automatic core attacks;
            # Mantis itself is acquired only by the native source operation.
            core=['tianxia.path.body_refining.feature.iron_fist']
            if cl>=5:core.append('tianxia.path.body_refining.feature.extra_attack')
            doc['path_and_subpath']={'path_feature_record_ids':core}
        if aid==FOE and foe_size is not None:doc['identity']['size']=foe_size
        if aid==FOE and foe_body:
            doc['identity']['path']='Body Refining'
            doc['path_and_subpath']={'path_feature_record_ids':['tianxia.path.body_refining.feature.body_tempering']}
        if aid==FOE and foe_kit:doc['equipment']=[{'starting_kit':foe_kit}]
        stats=doc['ability_scores_and_statistics']
        if owner and owner_str_score is not None:
            next(row for row in stats['abilities'] if row['ability']=='STR').update(score=owner_str_score,modifier=(owner_str_score-10)//2)
        if owner and owner_con_score is not None:
            next(row for row in stats['abilities'] if row['ability']=='CON').update(score=owner_con_score,modifier=(owner_con_score-10)//2)
        if aid==FOE and foe_saves is not None:stats['saving_throws']=foe_saves
        stats['primary_resource']['maximum']=owner_stamina if owner else 100
        stats['hit_points']['maximum']=foe_hp if aid==FOE else 1000
        stats['armor_class']['base_value']=5
        folder=tmp_path/'portable_characters'/aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    combat=CombatService(ROOT,tmp_path)
    combat.tabletop_maps.save({'map_id':'mantis-native','display_name':'Mantis native training yard',
        'width_squares':20,'height_squares':14,'objects':[],
        'starts':{'team1':[[3,6]],'team2':[[4,6],[3,7]]}})
    journey=combat.create_journey(project_ids=['worker2-owner','worker2-ally','worker2-foe'],
        arena_id='battlefield:map.mantis-native',positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:foe_position or {'x':4,'y':6}},
        base_paces={OWNER:3000,ALLY:3000,FOE:3000},control_modes=control_modes)
    if before_acquire:journey=before_acquire(combat,journey)
    acquired=combat.journey_acquire_source(journey['journey_id'],journey['revision'],OWNER,PARENT,{'operation':'select'})
    if before_combat:acquired=before_combat(combat,acquired)
    result=combat.journey_start_combat(journey['journey_id'],acquired['revision'],
        {OWNER:'team:factory',ALLY:'team:factory' if friendly_ally else 'team:opponents',FOE:'team:opponents'},maximum_rounds=maximum_rounds)
    table=TabletopService(combat,tmp_path);mid=result['match_id']
    if advance_owner:turn(table,mid,OWNER)
    return combat,table,mid


def strike(combat,mid,pincer=False,target=FOE):
    e=combat._load_session(mid).engine
    return next(c for c in e.legal_candidates() if c.target_ids==(target,)
        and '.natural.' in c.source_definition_id
        and bool(e.action_catalog[c.source_definition_id].parameters.get('rapid_pincer'))==pincer)



def hit(combat,table,mid,target=FOE,**kwargs):
    """Reach a real hit without scripting d20s or mutating a native roll result.

    The service chooses a random journey seed. A natural 1 spends the actual
    Attack action and advances initiative before another ordinary attempt.
    """
    prompts=[]
    for _ in range(5):
        before=combat._load_session(mid).engine.state.event_sequence
        prompts.extend(settle(table,mid,strike(combat,mid,target=target).candidate_id,**kwargs))
        e=combat._load_session(mid).engine
        if any(v.sequence>before and v.event_type=='DAMAGE_ROLLED' and v.actor_id==OWNER for v in e.events):return prompts
        turn(table,mid,FOE);turn(table,mid,OWNER)
    raise AssertionError('Five actual attacks all missed')


DECLINE={'choice:needle.mantis_hooks_light':None,'choice:needle.mantis_hooks':None,
    'choice:needle.path_hit.'+P+'death_of_a_thousand_cuts':None}
