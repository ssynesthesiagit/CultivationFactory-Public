"""Mantis native acquisition, table commits, cold replay guards."""
import json
import zipfile
import pytest
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
    from tests.test_r9i_karma_persistence import act
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
        chosen=picks.get(rid,'first' if rid.startswith('choice:') else None)
        count=counts.get(rid,0);counts[rid]=count+1
        if isinstance(chosen,tuple):chosen=chosen[min(count,len(chosen)-1)]
        answer={**context,'selection':'USE' if chosen is not None else 'DECLINE'}
        if chosen is not None and prompt.get('choice'):
            answer['option_ids']=([prompt['choice']['options'][0]['id']] if chosen=='first'
                else chosen if isinstance(chosen,list) else [chosen])
        answers.append(answer)


def native(tmp_path,cl=18,foe_kit=None,before_acquire=None,before_combat=None,control_modes=None,foe_saves=None,foe_body=False,friendly_ally=False,maximum_rounds=20,foe_talents=(),foe_size=None,foe_position=None,owner_stamina=100,owner_con_score=None,advance_owner=True):
    for aid,owner in ((OWNER,True),(ALLY,False),(FOE,False)):
        doc=sheet(list(foe_talents) if aid==FOE else [],cl=cl,primary='Stamina' if owner else 'Qi',score=30 if owner else 10,dc=100 if owner else 16,kit=foe_kit if aid==FOE else None,
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
        if owner and owner_con_score is not None:
            next(row for row in stats['abilities'] if row['ability']=='CON').update(score=owner_con_score,modifier=(owner_con_score-10)//2)
        if aid==FOE and foe_saves is not None:stats['saving_throws']=foe_saves
        stats['primary_resource']['maximum']=owner_stamina if owner else 100
        stats['hit_points']['maximum']=1000
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


def test_acquisition_derives_all_five_from_installed_body_progression(tmp_path):
    combat,table,mid=native(tmp_path)
    e=reload(tmp_path,mid)
    assert len([r for r in e.typed_passive_rows[OWNER] if str(r.get('feature_id','')).startswith(P)])>=3
    assert candidate(combat,mid,'Eye of the Mantis',target=FOE)
    assert not any('Mantis' in e.action_catalog[a].display_name for a in e.state.actors[FOE].action_ids)


def test_hooks_light_precedes_all_damage_dice_and_uses_target_choice(tmp_path):
    combat,table,mid=native(tmp_path)
    prompts=hit(combat,table,mid,picks={
        'choice:needle.mantis_hooks_light':'light','choice:needle.mantis_hooks':'grapple',
        'choice:needle.save_choice':'STR',
        'choice:needle.path_hit.'+P+'death_of_a_thousand_cuts':None})
    e=reload(tmp_path,mid)
    rolls=[r for r in e.rolls if r.reason.startswith('DAMAGE:') and r.actor_id==OWNER]
    assert rolls and not rolls[0].dice
    assert next(v.payload['reduced_to'] for v in e.events if v.event_type=='DAMAGE_COMMITTED' and v.actor_id==OWNER)==10
    hold=next(c for c in e.state.actors[FOE].conditions.values() if c.condition_id.endswith('.grappled'))
    assert hold.source_actor_id==OWNER and hold.data['grappling_part'].startswith('hand:')
    saves=[r for r in e.rolls if r.reason.startswith('SAVE:') and r.actor_id==FOE]
    assert saves[-1].reason.endswith(':STR') and saves[-1].mode=='DISADVANTAGE'
    assert any(p['context']['reactor_id']==FOE for p in prompts)


DECLINE={'choice:needle.mantis_hooks_light':None,'choice:needle.mantis_hooks':None,
    'choice:needle.path_hit.'+P+'death_of_a_thousand_cuts':None}


def test_joint_lock_cost_failure_expiry_and_release_are_native(tmp_path):
    combat,table,mid=native(tmp_path)
    assert not any(c.display_name=='Joint Lock' for c in combat._load_session(mid).engine.legal_candidates())
    hit(combat,table,mid,picks={**DECLINE,'choice:needle.mantis_hooks':'grapple'})
    e=reload(tmp_path,mid)
    assert any(c.condition_id.endswith('.grappled') for c in e.state.actors[FOE].conditions.values())
    settle(table,mid,candidate(combat,mid,'Joint Lock',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources[STAMINA]==99
    assert any(c.condition_id.endswith('.restrained') for c in e.state.actors[FOE].conditions.values())
    release=next(c for c in e.legal_candidates() if c.display_name=='Release grapple')
    settle(table,mid,release.candidate_id)
    assert not any(c.condition_id.endswith('.restrained') for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())


def test_pincer_two_sequential_targets_and_once_per_turn(tmp_path):
    combat,table,mid=native(tmp_path)
    settle(table,mid,strike(combat,mid,True).candidate_id,picks={**DECLINE,
        'choice:needle.pincer_target':(FOE,ALLY)})
    e=reload(tmp_path,mid)
    attacks=[v for v in e.events if v.event_type=='ATTACK_ROLLED' and v.actor_id==OWNER]
    assert len(attacks)==5
    assert [v.target_ids for v in attacks]==[(FOE,),(ALLY,),(ALLY,),(ALLY,),(ALLY,)]
    assert e.state.actors[OWNER].turn_flags['_round_rapid_pincer']
    assert len([r for r in e.rolls if r.reason.startswith('DAMAGE:') and r.actor_id==OWNER])<=5


def test_eye_native_private_profile_and_first_attack_mode(tmp_path):
    combat,table,mid=native(tmp_path)
    settle(table,mid,candidate(combat,mid,'Eye of the Mantis',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources[STAMINA]==97
    rows=combat.observer_readings(mid,OWNER)
    profile=next(r['details']['profile'] for r in rows if r['details'].get('feature')=='Eye of the Mantis')
    assert set(profile)=={'current_hp','maximum_hp','armor_class','resistances','immunities','concentration','physical_conditions','lowest_physical_saves'}
    assert profile['current_hp']==1000 and profile['maximum_hp']==1000 and profile['armor_class']==5
    assert profile['lowest_physical_saves']==['STR','DEX','CON']
    assert combat.observer_readings(mid,ALLY)==[] and combat.observer_readings(mid,FOE)==[]
    settle(table,mid,strike(combat,mid,True).candidate_id,picks={**DECLINE,'choice:needle.pincer_target':FOE})
    e=reload(tmp_path,mid)
    rolls=[r for r in e.rolls if r.reason.startswith('ATTACK:') and r.actor_id==OWNER]
    assert [r.mode for r in rolls]==['ADVANTAGE','NORMAL','NORMAL','NORMAL','NORMAL']


@pytest.mark.parametrize('rider',['No Reactions','Speed 0','Disadvantage on its next Concentration save','Disadvantage against your Grapple or Joint Lock'])
def test_cuts_one_paid_packet_and_selected_rider(tmp_path,rider):
    combat,table,mid=native(tmp_path)
    hit(combat,table,mid,picks={**DECLINE,
        'choice:needle.mantis_damage_type':'PIERCING',
        'choice:needle.path_hit.'+P+'death_of_a_thousand_cuts':rider})
    e=reload(tmp_path,mid);foe=e.state.actors[FOE]
    assert e.state.actors[OWNER].resources[STAMINA]==96
    assert len([r for r in e.rolls if r.reason=='MANTIS_CUTS_DAMAGE'])==1
    packets=[v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and v.actor_id==OWNER and v.target_ids==(FOE,)]
    assert len(packets)==len([v for v in e.events if v.event_type=='DAMAGE_ROLLED' and v.actor_id==OWNER])
    if rider=='Speed 0':assert e._effective_speed(foe)==0
    elif rider=='No Reactions':
        from combat.typed_executor import condition_rules
        assert any(r.get('no_reactions') for r in condition_rules(foe))
    else:assert any(c.condition_id=='condition:typed.mantis_cuts_next_save' for c in foe.conditions.values())


@pytest.mark.parametrize('cl,count',[(3,1),(6,2),(10,3),(14,4),(18,5)])
def test_open_school_progression_never_grants_future_features(tmp_path,cl,count):
    combat,table,mid=native(tmp_path,cl)
    journeys=list((tmp_path/'Combat'/'Journeys').glob('*.json'))
    e=reload(tmp_path,mid)
    owned={r.get('feature_id') for r in e.typed_passive_rows[OWNER]}
    actions=[e.action_catalog[a].parameters.get('typed',{}).get('source') for a in e.state.actors[OWNER].action_ids]
    for f,level in {'mantis_hooks':3,'joint_lock':6,'rapid_pincer':10,'eye_of_the_mantis':14,'death_of_a_thousand_cuts':18}.items():
        assert ((P+f in owned) or (P+f in actions))==(cl>=level)


def test_cuts_and_hooks_keep_non_damage_rider_when_normal_damage_replaced(tmp_path):
    combat,table,mid=native(tmp_path)
    hit(combat,table,mid,picks={**DECLINE,
        'choice:needle.mantis_hooks_light':'light','choice:needle.mantis_hooks':'grapple',
        'choice:needle.path_hit.'+P+'death_of_a_thousand_cuts':'Speed 0'})
    e=reload(tmp_path,mid)
    assert next(v.payload['reduced_to'] for v in e.events if v.event_type=='DAMAGE_COMMITTED' and v.actor_id==OWNER)==10
    assert not any(r.reason=='MANTIS_CUTS_DAMAGE' for r in e.rolls)
    assert e.state.actors[OWNER].resources[STAMINA]==96
    assert e._effective_speed(e.state.actors[FOE])==0
    assert any(c.condition_id.endswith('.grappled') for c in e.state.actors[FOE].conditions.values())


def test_eye_diagnosis_is_snapshot_and_expires_after_one_minute(tmp_path):
    combat,table,mid=native(tmp_path)
    settle(table,mid,candidate(combat,mid,'Eye of the Mantis',target=FOE).candidate_id)
    snapshot=combat.observer_readings(mid,OWNER)
    hit(combat,table,mid,picks=DECLINE)
    assert combat.observer_readings(mid,OWNER)==snapshot
    # Native turns advance the ordinary six-second combat clock.
    for _ in range(10):
        turn(table,mid,FOE);turn(table,mid,OWNER)
    e=reload(tmp_path,mid)
    assert not any(c.condition_id=='condition:typed.eye_of_the_mantis' for c in e.state.actors[FOE].conditions.values())
    assert combat.observer_readings(mid,OWNER)==[]


def test_mixed_cuts_are_one_native_damage_commit(tmp_path):
    combat,table,mid=native(tmp_path)
    hit(combat,table,mid,picks={**DECLINE,
        'choice:needle.mantis_damage_type':'BLUDGEONING',
        'choice:needle.path_hit.'+P+'death_of_a_thousand_cuts':'No Reactions'})
    e=reload(tmp_path,mid)
    packets=[v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and v.actor_id==OWNER and v.target_ids==(FOE,)]
    mixed=[v for v in packets if v.payload['damage_type']=='MIXED']
    assert len(mixed)==1
    packet=mixed[0].payload
    assert packet['damage_type']=='MIXED'
    assert [c['damage_type'] for c in packet['damage_components']]==['BLUDGEONING','PIERCING']
    assert packet['rolled_or_pending_damage']==sum(c['amount'] for c in packet['damage_components'])


def test_low_level_and_wrong_path_cannot_acquire_mantis(tmp_path):
    with pytest.raises(ValueError,match='CL3'):
        native(tmp_path,2)


def test_joint_lock_ends_at_start_of_source_next_turn(tmp_path):
    combat,table,mid=native(tmp_path)
    hit(combat,table,mid,picks={**DECLINE,'choice:needle.mantis_hooks':'grapple'})
    settle(table,mid,candidate(combat,mid,'Joint Lock',target=FOE).candidate_id)
    turn(table,mid,FOE)
    assert any(c.condition_id.endswith('.restrained') for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())
    turn(table,mid,OWNER)
    assert not any(c.condition_id.endswith('.restrained') for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())


def test_cuts_drops_exact_native_held_object_after_failed_save(tmp_path):
    from tests.auto11_service_support import SWORD
    from combat.ext.scoundrel_riders import held_possessions
    combat,table,mid=native(tmp_path,foe_kit=SWORD)
    initial=reload(tmp_path,mid)
    held=held_possessions(initial,initial.state.actors[FOE]);assert len(held)==1
    prompts=hit(combat,table,mid,picks={**DECLINE,
        'choice:needle.path_hit.'+P+'death_of_a_thousand_cuts':'Drop a held object'})
    e=reload(tmp_path,mid)
    assert held_possessions(e,e.state.actors[FOE])==[]
    dropped=next(c for c in e.state.actors[FOE].conditions.values() if c.data.get('object_id')==held[0]['object'])
    assert dropped.data['dropped_at']==e.state.actors[FOE].position.model_dump(mode='json')
    assert any(p['context']['reaction_source_id']=='choice:needle.mantis_drop' for p in prompts)


def test_eye_travel_activation_private_reading_and_combat_continuation(tmp_path):
    def travel(combat,state):
        jid=state['journey_id'];options=combat.journey_menu(jid,OWNER)['options']
        option=next(o for o in options if o['id']=='mantis_eye:'+FOE)
        state=combat.journey_act(jid,state['revision'],OWNER,option['kind'],option['payload'])
        assert state['actors'][OWNER]['resources'][STAMINA]==97
        assert combat.journey_menu(jid,OWNER)['properties']['mantis_private_diagnosis']['profile']['current_hp']==1000
        assert 'mantis_private_diagnosis' not in combat.journey_menu(jid,FOE)['properties']
        return combat.journey_act(jid,state['revision'],OWNER,'wait',{'seconds':59})
    combat,table,mid=native(tmp_path,before_combat=travel,advance_owner=False)
    assert combat.observer_readings(mid,OWNER)
    engine=reload(tmp_path,mid)
    mark=next(c for c in engine.state.actors[FOE].conditions.values() if c.condition_id=='condition:typed.eye_of_the_mantis')
    from combat.ext.mantis_style import eye_remaining
    assert eye_remaining(engine,mark)==1
    assert engine.state.actors[OWNER].resources[STAMINA]==97
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert not combat.observer_readings(mid,OWNER)
    assert reload(tmp_path,mid).state.actors[OWNER].resources[STAMINA]==97


@pytest.mark.parametrize('source_cl,authority,concealed',[(18,'ordinary',True),(3,'protected',True),(3,'ordinary',False)])
def test_eye_concealment_comes_from_native_gm_input_not_target_metadata(tmp_path,source_cl,authority,concealed):
    def declare(combat,state):
        return combat.journey_world_fact(state['journey_id'],state['revision'],{
            'source':PARENT,'subject':FOE,'kind':'diagnosis_concealment','scope':'concealing ward',
            'value':{'effect_source':'native GM ward','source_cl':source_cl,'save_dc':100,'authority':authority,
                'data':['current_hp','maximum_hp','lowest_physical_saves']},
            'expires_at':60,'readers':[FOE]})
    combat,table,mid=native(tmp_path,before_acquire=declare)
    settle(table,mid,candidate(combat,mid,'Eye of the Mantis',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    profile=combat.observer_readings(mid,OWNER)[0]['details']['profile']
    assert profile['current_hp']==('concealed' if concealed else 1000)
    assert profile['maximum_hp']==('concealed' if concealed else 1000)
    assert profile['lowest_physical_saves']==('concealed' if concealed else ['STR','DEX','CON']) and profile['armor_class']==5
    assert any(v.event_type=='CHECK_ROLLED' and v.actor_id==OWNER for v in e.events)==concealed
    assert 'vs DC 100' not in str(table.events(mid,0))


def test_wrong_owner_and_unknown_acquisition_are_inert(tmp_path):
    def guard(combat,state):
        jid=state['journey_id'];revision=state['revision']
        with pytest.raises(ValueError,match='Body Refining'):
            combat.journey_acquire_source(jid,revision,FOE,PARENT,{'operation':'select'})
        assert combat.journey_state(jid)==state
        with pytest.raises(ValueError,match='unique native acquisition'):
            combat.journey_acquire_source(jid,revision,OWNER,'unknown school',{'operation':'select'})
        assert combat.journey_state(jid)==state
        return state
    native(tmp_path,before_acquire=guard)


def test_hooks_and_cuts_remain_once_per_turn_in_replacement_sequence(tmp_path):
    combat,table,mid=native(tmp_path)
    prompts=settle(table,mid,strike(combat,mid,True).candidate_id,picks={**DECLINE,
        'choice:needle.pincer_target':FOE,'choice:needle.mantis_hooks':'grapple',
        'choice:needle.path_hit.'+P+'death_of_a_thousand_cuts':'Speed 0'})
    e=reload(tmp_path,mid)
    assert len([r for r in e.rolls if r.reason=='MANTIS_CUTS_DAMAGE'])<=1
    assert len([r for r in e.rolls if r.reason.startswith('SAVE:'+P+'mantis_hooks')])<=1
    assert e.state.actors[OWNER].resources[STAMINA] in (96,100)


def test_ai_attack_preserves_manual_defender_save_choice(tmp_path):
    combat,table,mid=native(tmp_path,control_modes={OWNER:'LOCAL_AUTO',ALLY:'MANUAL',FOE:'MANUAL'})
    seen=[]
    for _ in range(12):
        turn(table,mid,OWNER)
        seen.extend(settle(table,mid,'automatic native decision',auto=True,
            picks={'choice:needle.save_choice':'STR'}))
        reload(tmp_path,mid)
        if any(p['context']['reaction_source_id']=='choice:needle.save_choice' for p in seen):break
    saves=[p for p in seen if p['context']['reaction_source_id']=='choice:needle.save_choice']
    assert saves and all(p['context']['reactor_id'] in (FOE,ALLY) for p in saves)


def test_artifact_flag_from_installed_native_inventory_guards_drop_option(tmp_path):
    from tests.auto11_service_support import SWORD
    from copy import deepcopy
    kit=deepcopy(SWORD);kit['items'][0]['artifact']=1
    combat,table,mid=native(tmp_path,foe_kit=kit)
    e=reload(tmp_path,mid)
    from combat.ext.scoundrel_riders import held_possessions
    items=held_possessions(e,e.state.actors[FOE])
    assert len(items)==1 and items[0]['artifact']==1
    prompts=hit(combat,table,mid,picks={**DECLINE,
        'choice:needle.path_hit.'+P+'death_of_a_thousand_cuts':'Speed 0'})
    menu=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.path_hit.'+P+'death_of_a_thousand_cuts')
    assert 'Drop a held object' not in {o['id'] for o in menu['choice']['options']}
    e=reload(tmp_path,mid)
    assert held_possessions(e,e.state.actors[FOE])


def test_successful_joint_lock_save_still_denies_reactions_until_source_turn(tmp_path):
    combat,table,mid=native(tmp_path,foe_saves={'STR':0,'DEX':100,'CON':0})
    hit(combat,table,mid,picks={**DECLINE,'choice:needle.mantis_hooks':'grapple','choice:needle.save_choice':'STR'})
    settle(table,mid,candidate(combat,mid,'Joint Lock',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    from combat.typed_executor import condition_rules
    assert not any(c.condition_id.endswith('.restrained') for c in e.state.actors[FOE].conditions.values())
    assert any(r.get('no_reactions') for r in condition_rules(e.state.actors[FOE]))
    turn(table,mid,FOE);turn(table,mid,OWNER)
    e=reload(tmp_path,mid)
    assert not any(r.get('no_reactions') for r in condition_rules(e.state.actors[FOE]))


def test_eye_grapple_and_joint_lock_save_benefits_have_separate_receipts(tmp_path):
    combat,table,mid=native(tmp_path)
    settle(table,mid,candidate(combat,mid,'Eye of the Mantis',target=FOE).candidate_id)
    turn(table,mid,FOE);turn(table,mid,OWNER)
    hit(combat,table,mid,picks={**DECLINE,'choice:needle.mantis_hooks':'grapple','choice:needle.save_choice':'STR'})
    settle(table,mid,candidate(combat,mid,'Joint Lock',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    grip_saves=[r for r in e.rolls if r.reason.startswith('SAVE:'+P+'mantis_hooks')]
    lock_saves=[r for r in e.rolls if P+'joint_lock' in r.reason and r.reason.startswith('SAVE:')]
    assert grip_saves and grip_saves[-1].mode=='DISADVANTAGE'
    assert lock_saves and lock_saves[-1].mode=='DISADVANTAGE'
    eye=next(c for c in e.state.actors[FOE].conditions.values() if c.condition_id=='condition:typed.eye_of_the_mantis')
    assert eye.data.get('lock_turn') and eye.data.get('attack_turn')


def test_eye_reads_conditional_native_resistances_without_revealing_sources(tmp_path):
    combat,table,mid=native(tmp_path,foe_body=True)
    settle(table,mid,candidate(combat,mid,'Eye of the Mantis',target=FOE).candidate_id)
    reload(tmp_path,mid)
    profile=combat.observer_readings(mid,OWNER)[0]['details']['profile']
    assert all(any(kind in row and 'nonmagical' in row for row in profile['resistances'])
        for kind in ('Bludgeoning','Piercing','Slashing'))
    assert 'Body Tempering' not in str(profile)
    assert 'vulnerabilities' not in profile


def test_hooks_can_affect_a_hit_ally_without_assuming_willingness(tmp_path):
    combat,table,mid=native(tmp_path,friendly_ally=True)
    prompts=hit(combat,table,mid,target=ALLY,picks={**DECLINE,
        'choice:needle.mantis_hooks':'grapple','choice:needle.save_choice':'STR'})
    e=reload(tmp_path,mid)
    assert any(c.condition_id.endswith('.grappled') and c.source_actor_id==OWNER for c in e.state.actors[ALLY].conditions.values())
    assert any(v.event_type=='SAVE_ROLLED' and v.actor_id==ALLY for v in e.events)
    assert any(p['context']['reactor_id']==ALLY and p['context']['reaction_source_id']=='choice:needle.save_choice' for p in prompts)


def test_eye_combat_terminal_to_travel_preserves_private_snapshot_and_remaining_clock(tmp_path):
    captured = {}
    def remember(combat, state):
        captured['jid'] = state['journey_id']
        return state
    combat, table, mid = native(tmp_path, before_combat=remember, maximum_rounds=2)
    settle(table, mid, candidate(combat, mid, 'Eye of the Mantis', target=FOE).candidate_id)
    profile = combat.observer_readings(mid, OWNER)[0]['details']['profile']
    for _ in range(10):
        if reload(tmp_path, mid).state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    terminal = reload(tmp_path, mid)
    assert terminal.state.terminal_result is not None
    terminal_bytes = terminal.state.model_dump_json()
    jid = captured['jid']
    cold = CombatService(ROOT, tmp_path)
    state = cold.journey_state(jid)
    resumed = cold.journey_resume(jid, state['revision'])
    assert reload(tmp_path, mid).state.model_dump_json() == terminal_bytes
    reading = cold.journey_menu(jid, OWNER)['properties']['mantis_private_diagnosis']
    assert reading['profile'] == profile
    remaining = reading['remaining_num'] / reading['remaining_den']
    assert 0 < remaining < 60
    assert 'mantis_private_diagnosis' not in cold.journey_menu(jid, FOE)['properties']
    assert resumed['actors'][OWNER]['resources'][STAMINA] == terminal.state.actors[OWNER].resources[STAMINA]
    state = cold.journey_act(jid, resumed['revision'], OWNER, 'wait', {'seconds':60})
    assert 'mantis_private_diagnosis' not in cold.journey_menu(jid, OWNER)['properties']


def test_cuts_next_grapple_save_is_consumed_by_the_actual_native_roll(tmp_path):
    combat, table, mid = native(tmp_path)
    hit(combat, table, mid, picks={**DECLINE,
        'choice:needle.path_hit.'+P+'death_of_a_thousand_cuts':'Disadvantage against your Grapple or Joint Lock'})
    assert any(c.condition_id=='condition:typed.mantis_cuts_next_save'
               for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())
    turn(table, mid, FOE); turn(table, mid, OWNER)
    hit(combat, table, mid, picks={**DECLINE,'choice:needle.mantis_hooks':'grapple'})
    engine = reload(tmp_path,mid)
    saves = [r for r in engine.rolls if r.reason.startswith('SAVE:'+P+'mantis_hooks')]
    assert saves and saves[-1].mode == 'DISADVANTAGE'
    assert not any(c.condition_id=='condition:typed.mantis_cuts_next_save'
                   for c in engine.state.actors[FOE].conditions.values())


def test_cuts_concentration_rider_uses_real_cast_and_only_next_damage_save(tmp_path):
    combat, table, mid = native(tmp_path,foe_talents=['FIRE_TAL_BURNING_WEAPON'],
        foe_saves={'STR':0,'DEX':0,'CON':100})
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Burning Weapon').candidate_id)
    from combat import concentration
    assert concentration.sources(reload(tmp_path,mid).state.actors[FOE])
    turn(table,mid,OWNER)
    hit(combat,table,mid,picks={**DECLINE,
        'choice:needle.path_hit.'+P+'death_of_a_thousand_cuts':'Disadvantage on its next Concentration save'})
    engine=reload(tmp_path,mid)
    saves=[r for r in engine.rolls if r.reason.startswith('SAVE:system:combat.concentration')]
    assert saves and saves[0].mode=='DISADVANTAGE'
    assert all(r.mode=='NORMAL' for r in saves[1:])
    assert not any(c.condition_id=='condition:typed.mantis_cuts_next_save'
                   for c in engine.state.actors[FOE].conditions.values())


@pytest.mark.parametrize('size,allowed',[('Large',True),('Huge',False)])
def test_hooks_native_creature_size_boundary_preserves_the_hit(tmp_path,size,allowed):
    combat,table,mid=native(tmp_path,foe_size=size)
    assert reload(tmp_path,mid).state.actors[FOE].size_category.upper()==size.upper()
    prompts=hit(combat,table,mid,picks={**DECLINE,'choice:needle.mantis_hooks':'grapple'})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[FOE].current_hp < engine.state.actors[FOE].maximum_hp
    held=any(c.condition_id.endswith('.grappled') and c.source_actor_id==OWNER
             for c in engine.state.actors[FOE].conditions.values())
    assert held == allowed
    assert any(p['context']['reaction_source_id']=='choice:needle.mantis_hooks' for p in prompts) == allowed


@pytest.mark.parametrize('x,available',[(15,True),(16,False)])
def test_eye_native_sixty_foot_boundary(tmp_path,x,available):
    combat,table,mid=native(tmp_path,foe_position={'x':x,'y':6})
    engine=reload(tmp_path,mid)
    choices=[c for c in engine.legal_candidates() if c.display_name=='Eye of the Mantis' and c.target_ids==(FOE,)]
    assert bool(choices)==available
    if available:
        settle(table,mid,choices[0].candidate_id)
        assert combat.observer_readings(mid,OWNER)[0]['details']['target_id']==FOE
        reload(tmp_path,mid)


def test_cuts_insufficient_native_stamina_is_inert(tmp_path):
    combat,table,mid=native(tmp_path,owner_stamina=3)
    prompts=hit(combat,table,mid,picks=DECLINE)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources[STAMINA]==3
    assert not any(r.reason=='MANTIS_CUTS_DAMAGE' for r in engine.rolls)
    assert not any(p['context']['reaction_source_id']=='choice:needle.path_hit.'+P+'death_of_a_thousand_cuts' for p in prompts)


@pytest.mark.parametrize('rider',['Disadvantage on its next Concentration save','Disadvantage against your Grapple or Joint Lock'])
def test_cuts_unused_next_save_rider_expires_at_end_of_source_next_turn(tmp_path,rider):
    combat,table,mid=native(tmp_path)
    hit(combat,table,mid,picks={**DECLINE,'choice:needle.path_hit.'+P+'death_of_a_thousand_cuts':rider})
    turn(table,mid,FOE);turn(table,mid,OWNER)
    assert any(c.condition_id=='condition:typed.mantis_cuts_next_save'
               for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert not any(c.condition_id=='condition:typed.mantis_cuts_next_save'
                   for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())


@pytest.mark.parametrize('score,damage',[(8,0),(18,4)])
def test_hooks_light_uses_each_native_chosen_attack_modifier_with_zero_floor(tmp_path,score,damage):
    combat,table,mid=native(tmp_path,owner_con_score=score)
    prompts=hit(combat,table,mid,picks={**DECLINE,
        'choice:needle.mantis_attack_ability':'CON',
        'choice:needle.mantis_hooks_light':'light','choice:needle.mantis_hooks':'grapple'})
    engine=reload(tmp_path,mid)
    packet=next(e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.actor_id==OWNER)
    assert packet.payload['reduced_to']==damage
    roll=next(r for r in engine.rolls if r.reason.startswith('DAMAGE:') and r.actor_id==OWNER)
    assert not roll.dice
    assert any(p['context']['reaction_source_id']=='choice:needle.mantis_attack_ability' for p in prompts)
    assert any(c.condition_id.endswith('.grappled') and c.source_actor_id==OWNER
               for c in engine.state.actors[FOE].conditions.values())
