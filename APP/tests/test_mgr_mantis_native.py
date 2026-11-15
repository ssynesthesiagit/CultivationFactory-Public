"""Mantis native acquisition, table commits, cold replay guards."""
import json
import zipfile
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from combat.ext.mantis_style import LEVELS
from tests.worker2_support import OWNER, ALLY, FOE, candidate, reload, turn

from tests.mantis_native_support import PARENT, P, STAMINA, settle, native, strike, hit, DECLINE

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
    # The normal seat-owned tabletop projection delivers plain readable text
    # only to the practitioner; direct service reads alone are not delivery.
    own_view=table.state(mid,fog=True,fog_view='own',fog_actor_ids=(OWNER,))
    text=' '.join(own_view['observer_information'][OWNER]['information_text'])
    assert 'Eye of the Mantis' in text and '1000/1000 Hit Points' in text and 'Armor Class 5' in text
    other_view=table.state(mid,fog=True,fog_view='own',fog_actor_ids=(FOE,))
    assert not other_view.get('observer_information',{}).get(FOE)
    settle(table,mid,strike(combat,mid,True).candidate_id,picks={**DECLINE,'choice:needle.pincer_target':FOE})
    e=reload(tmp_path,mid)
    rolls=[r for r in e.rolls if r.reason.startswith('ATTACK:') and r.actor_id==OWNER]
    assert [r.mode for r in rolls]==['ADVANTAGE','NORMAL','NORMAL','NORMAL','NORMAL']


@pytest.mark.parametrize('rider',['No Reactions','Speed 0','Disadvantage on its next Concentration save','Disadvantage against your Grapple or Joint Lock'])
def test_cuts_one_paid_packet_and_selected_rider(tmp_path,rider):
    combat,table,mid=native(tmp_path)
    hit(combat,table,mid,picks={**DECLINE,
        'choice:needle.iron_fist_damage_type':'PIERCING',
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


def test_mixed_packet_flat_reduction_is_capped_by_eligible_type(monkeypatch):
    from types import SimpleNamespace
    from combat import typed_reactions
    target=SimpleNamespace(turn_flags={},modifiers={},entity_id='target')
    engine=SimpleNamespace(_append_event=lambda *a,**k:None)
    def defend(_engine,_target,amount,kind,*args,**kwargs):
        found={'reduction_sources':{'padded-layers':6} if kind=='BLUDGEONING' else {},
            'reduction':0,'per_round':[],'once':[],'resistance_next':[],
            'resist':False,'resistance_suppressed':False}
        return amount,found
    monkeypatch.setattr(typed_reactions,'defend',defend)
    from combat import ext
    monkeypatch.setattr(ext,'callbacks',lambda _name:[])
    monkeypatch.setattr(ext,'run',lambda *args,**kwargs:[])
    monkeypatch.setattr(ext,'run_strict',lambda *args,**kwargs:[])
    # This isolates the flat-reduction path: the whole-hit before-Resistance phase
    # asks the pure defense question separately, and these stubs answer only rows.
    monkeypatch.setattr(typed_reactions,'_defenses',lambda *a,**k:{'immune':False,'pre_reduction_sources':{}})
    assert typed_reactions.defend_components(engine,target,[(2,'BLUDGEONING'),(20,'PIERCING')],None,None)==20



def test_mixed_packet_stacked_reductions_share_only_covered_damage(monkeypatch):
    from types import SimpleNamespace
    from combat import typed_reactions
    target=SimpleNamespace(turn_flags={},modifiers={},entity_id='target')
    engine=SimpleNamespace(_append_event=lambda *a,**k:None)
    def defend(_engine,_target,amount,kind,*args,**kwargs):
        found={'reduction_sources':({f'layer-{i}':2 for i in range(2)} if kind=='BLUDGEONING' else {}),
            'reduction':0,'per_round':[],'once':[],'resistance_next':[],
            'resist':False,'resistance_suppressed':False}
        return amount,found
    monkeypatch.setattr(typed_reactions,'defend',defend)
    from combat import ext
    monkeypatch.setattr(ext,'callbacks',lambda _name:[])
    monkeypatch.setattr(ext,'run',lambda *args,**kwargs:[])
    monkeypatch.setattr(ext,'run_strict',lambda *args,**kwargs:[])
    # This isolates the flat-reduction path: the whole-hit before-Resistance phase
    # asks the pure defense question separately, and these stubs answer only rows.
    monkeypatch.setattr(typed_reactions,'_defenses',lambda *a,**k:{'immune':False,'pre_reduction_sources':{}})
    assert typed_reactions.defend_components(engine,target,[(2,'BLUDGEONING'),(20,'PIERCING')],None,None)==20


def test_mixed_cuts_are_one_native_damage_commit(tmp_path):
    combat,table,mid=native(tmp_path)
    hit(combat,table,mid,picks={**DECLINE,
        'choice:needle.iron_fist_damage_type':'BLUDGEONING',
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


def test_source_acquisition_seam_rejects_fabricated_receipts_and_stale_revisions(tmp_path):
    """Acquisition is one native seam: no sheet, no earned feature list, no stale write."""
    captured={}
    def guard(combat,state):
        jid,revision=state['journey_id'],state['revision']
        captured['jid']=jid
        stable=combat.journey_state(jid)  # the committed snapshot, not the live working copy
        for payload in ({'operation':'select','feature_ids':[P+'rapid_pincer']},
                        {'operation':'select','access_receipt':'fabricated'},
                        {'operation':'grant','earned_features':[P+'mantis_hooks']}):
            # The provider refuses the payload, so no procedure accepts it.
            with pytest.raises(ValueError,match='fabricated receipts'):
                combat.journey_acquire_source(jid,revision,OWNER,PARENT,payload)
            assert combat.journey_state(jid)==stable
        with pytest.raises(ValueError,match='changed'):
            combat.journey_acquire_source(jid,revision-1,OWNER,PARENT,{'operation':'select'})
        assert combat.journey_state(jid)==stable
        return state
    combat,table,mid=native(tmp_path,before_acquire=guard)
    # Earned milestones live in the source overlay the fight compiled from;
    # passive rows only exist for printed passive features.
    overlay=combat.journey_state(captured['jid'])['actors'][OWNER]['source_states'][PARENT]['sheet']
    assert {P+name for name in LEVELS}<=set(overlay['path_feature_record_ids'])
    assert overlay['subpath_acquisition']['earned_features']==[P+name for name,level in LEVELS.items() if level<=18]
    engine=combat._load_session(mid).engine
    assert len([c for c in engine.legal_candidates() if 'Pincer' in c.display_name])>0


@pytest.mark.parametrize('source_cl,authority,concealed',[(18,'ordinary',True),(3,'protected',True),(3,'ordinary',False)])
def test_eye_concealment_comes_from_native_gm_input_not_target_metadata(tmp_path,source_cl,authority,concealed):
    def declare(combat,state):
        return admit_fact(combat,state,{
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
        stable=combat.journey_state(jid)  # the committed snapshot, not the live working copy
        with pytest.raises(ValueError,match='Body Refining'):
            combat.journey_acquire_source(jid,revision,FOE,PARENT,{'operation':'select'})
        assert combat.journey_state(jid)==stable
        with pytest.raises(ValueError,match='Exactly one source provider'):
            combat.journey_acquire_source(jid,revision,OWNER,'unknown school',{'operation':'select'})
        assert combat.journey_state(jid)==stable
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


@pytest.mark.parametrize('flag',['artifact','soul_bound','sealed'])
def test_artifact_flag_from_installed_native_inventory_guards_drop_option(tmp_path,flag):
    from tests.auto11_service_support import SWORD
    from copy import deepcopy
    kit=deepcopy(SWORD);kit['items'][0][flag]=1
    combat,table,mid=native(tmp_path,foe_kit=kit)
    e=reload(tmp_path,mid)
    from combat.ext.scoundrel_riders import held_possessions
    items=held_possessions(e,e.state.actors[FOE])
    assert len(items)==1 and items[0][flag]==1
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
    save=next(e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.source_definition_id==P+'mantis_hooks')
    # Fixed damage does not advance the random counter, so its receipt may
    # share the next save's roll ID. Identify the actual native save as well.
    rolled=next(r for r in engine.rolls if r.roll_id==save.payload['roll_id']
                and r.reason==save.payload['reason'])
    held=any(c.condition_id.endswith('.grappled') and c.source_actor_id==OWNER
             for c in engine.state.actors[FOE].conditions.values())
    assert held==(rolled.total<save.payload['dc'])
    assert rolled.mode=='DISADVANTAGE'


@pytest.mark.parametrize('score,damage',[(8,0),(18,4)])
def test_hooks_light_disadvantage_reaches_the_save_seam_without_the_light_choice_it_is_normal(tmp_path,score,damage):
    """The disadvantage is a save-seam modifier, not narration on the prompt."""
    picks={**DECLINE,'choice:needle.mantis_attack_ability':'CON','choice:needle.mantis_hooks':'grapple'}
    combat,table,mid=native(tmp_path,owner_con_score=score)
    hit(combat,table,mid,picks={**picks,'choice:needle.mantis_hooks_light':'light'})
    light=reload(tmp_path,mid)
    save=next(e for e in light.events if e.event_type=='SAVE_ROLLED' and e.source_definition_id==P+'mantis_hooks')
    rolled=next(r for r in light.rolls if r.roll_id==save.payload['roll_id'] and r.reason==save.payload['reason'])
    assert rolled.mode=='DISADVANTAGE' and rolled.dice
    assert any(e.event_type=='DAMAGE_COMMITTED' and e.payload.get('reduced_to')==damage for e in light.events if e.actor_id==OWNER)
    plain_root=tmp_path/'plain';plain_root.mkdir()
    combat2,table2,mid2=native(plain_root,owner_con_score=score)
    hit(combat2,table2,mid2,picks=picks)
    bare=reload(plain_root,mid2)
    save2=next(e for e in bare.events if e.event_type=='SAVE_ROLLED' and e.source_definition_id==P+'mantis_hooks')
    rolled2=next(r for r in bare.rolls if r.roll_id==save2.payload['roll_id'] and r.reason==save2.payload['reason'])
    assert rolled2.mode=='NORMAL' and save2.payload['dc']==save.payload['dc']


def concealment_fact(*,expires=60):
    return {'source':PARENT,'subject':FOE,'kind':'diagnosis_concealment','scope':'native concealing ward',
        'value':{'effect_source':'native GM ward','source_cl':18,'save_dc':100,'data':['current_hp']},
        'expires_at':expires,'readers':[FOE]}


def admit_fact(combat,state,fact=None):
    """Table-owner travel declaration through the one native GM admission seam."""
    fact=fact or concealment_fact()
    body={k:v for k,v in fact.items() if k not in ('subject','kind')}
    return combat.journey_admit(state['journey_id'],state['revision'],fact['subject'],fact['kind'],body,
        gm=True,reason='native concealing ward')


def test_gm_concealment_after_acquisition_reaches_native_eye(tmp_path):
    def declare(combat,state):
        return admit_fact(combat,state)
    combat,table,mid=native(tmp_path,before_combat=declare)
    settle(table,mid,candidate(combat,mid,'Eye of the Mantis',target=FOE).candidate_id)
    assert combat.observer_readings(mid,OWNER)[0]['details']['profile']['current_hp']=='concealed'
    reload(tmp_path,mid)


def test_gm_concealment_document_is_validated_before_receipt_commit(tmp_path):
    def invalid(combat,state):
        payload=concealment_fact();payload['value']['data']=['hidden spell list']
        stable=combat.journey_state(state['journey_id'])  # the committed snapshot, not the live working copy
        with pytest.raises(ValueError,match='document schema'):
            admit_fact(combat,state,payload)
        assert combat.journey_state(state['journey_id'])==stable
        return state
    combat,table,mid=native(tmp_path,before_combat=invalid)
    reload(tmp_path,mid)


def test_admitted_concealment_exact_deadline_expires_on_next_native_clock_boundary(tmp_path):
    def declare(combat,state):
        return admit_fact(combat,state,concealment_fact(expires=1))
    combat,table,mid=native(tmp_path,before_acquire=declare,advance_owner=False)
    def wards():
        return [c for c in reload(tmp_path,mid).state.actors[FOE].conditions.values()
                if c.condition_id=='condition:typed.mantis_diagnosis_concealment']
    assert wards()
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert not wards()


def test_foreign_journey_fact_kind_is_refused_and_writes_nothing(tmp_path):
    def declare(combat,state):
        # A foreign fact kind is refused by every provider, so the Mantis
        # concealment provider cannot swallow another consumer's seam.
        stable=combat.journey_state(state['journey_id'])  # the committed snapshot, not the live working copy
        with pytest.raises(ValueError,match='not available'):
            admit_fact(combat,state,{
                'source':'system:journey.scene','subject':OWNER,'kind':'scene_end','scope':'training',
                'value':'The table owner records the scene boundary reason.','expires_at':1,'readers':[OWNER]})
        assert combat.journey_state(state['journey_id'])==stable
        return state
    combat,table,mid=native(tmp_path,before_combat=declare)
    assert not combat.observer_readings(mid,OWNER)
    assert not any(c.condition_id=='condition:typed.mantis_diagnosis_concealment'
                   for a in reload(tmp_path,mid).state.actors.values() for c in a.conditions.values())


@pytest.mark.parametrize('withdraw',[False,True])
def test_native_concealment_continues_then_ends_without_resurrecting_an_old_admission(tmp_path,withdraw):
    captured={}
    def declare(combat,state):
        captured['jid']=state['journey_id']
        return admit_fact(combat,state)
    combat,table,mid=native(tmp_path,before_acquire=declare,maximum_rounds=2)
    settle(table,mid,candidate(combat,mid,'Eye of the Mantis',target=FOE).candidate_id)
    assert combat.observer_readings(mid,OWNER)[0]['details']['profile']['current_hp']=='concealed'
    for _ in range(10):
        if reload(tmp_path,mid).state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    terminal=reload(tmp_path,mid)
    assert terminal.state.terminal_result is not None
    unchanged=terminal.state.model_dump_json()
    jid=captured['jid'];cold=CombatService(ROOT,tmp_path)
    state=cold.journey_state(jid)
    state=cold.journey_resume(jid,state['revision'])
    assert reload(tmp_path,mid).state.model_dump_json()==unchanged
    ledger=state['actors'][FOE]['source_states'][PARENT]['wards']
    saved=next(iter(ledger.values()))
    assert 0 < saved['remaining_num']/saved['remaining_den'] < 60
    if withdraw:
        payload=concealment_fact();payload['value']['active']=0
        state=admit_fact(cold,{'journey_id':jid,'revision':state['revision']},payload)
    else:
        from math import ceil
        from fractions import Fraction
        seconds=ceil(Fraction(saved['remaining_num'],saved['remaining_den']))
        assert seconds < 60  # the original declaration is still live on the journey clock
        state=cold.journey_act(jid,state['revision'],OWNER,'wait',{'seconds':seconds})
    option=next(o for o in cold.journey_menu(jid,OWNER)['options'] if o['id']=='mantis_eye:'+FOE)
    state=cold.journey_act(jid,state['revision'],OWNER,option['kind'],option['payload'])
    assert cold.journey_menu(jid,OWNER)['properties']['mantis_private_diagnosis']['profile']['current_hp']==1000
    assert 'mantis_private_diagnosis' not in cold.journey_menu(jid,FOE)['properties']
    assert state['actors'][OWNER]['resources'][STAMINA]==94
    # Finishing/reopening cannot revive a superseded/expired actual ward.
    state=cold.journey_act(jid,state['revision'],OWNER,'finish',{})
    reopened=cold.create_journey(project_ids=['worker2-owner','worker2-ally','worker2-foe'],
        arena_id='battlefield:map.mantis-native',positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':4,'y':6}},
        base_paces={OWNER:3000,ALLY:3000,FOE:3000})
    new_jid=reopened['journey_id']
    # The acquired school and its still-live reading are this creature's own
    # continuation: opening the next journey compiles what it actually learned,
    # so nothing is opened a second time and the unexpired Eye keeps running.
    assert any(a.get('display_name')=='Eye of the Mantis' for a in reopened['actors'][OWNER]['bundle']['action_catalog'])
    assert next(o for o in cold.journey_menu(new_jid,OWNER)['options'] if o['id']=='mantis_eye:'+FOE)
    assert cold.journey_menu(new_jid,OWNER)['properties']['mantis_private_diagnosis']['profile']['current_hp']==1000
    resumed=[saved for actor in reopened['actors'].values()
             for saved in actor.get('source_states',{}).get(PARENT,{}).get('wards',{}).values() if not saved.get('ended')]
    assert not resumed, 'a finished or superseded ward never comes back in a new journey'


def test_travel_resume_keeps_the_live_concealing_ward_until_it_expires(tmp_path):
    """The ward the encounter snapshot deliberately omits survives the travel projection."""
    from fractions import Fraction
    from math import ceil
    captured={}
    def declare(combat,state):
        captured['jid']=state['journey_id']
        return admit_fact(combat,state)
    combat,table,mid=native(tmp_path,before_acquire=declare,maximum_rounds=2)
    assert reload(tmp_path,mid).state.actors[OWNER].resources[STAMINA]==100
    settle(table,mid,candidate(combat,mid,'Eye of the Mantis',target=FOE).candidate_id)
    assert reload(tmp_path,mid).state.actors[OWNER].resources[STAMINA]==97
    for _ in range(10):
        if reload(tmp_path,mid).state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path,mid).state.terminal_result is not None
    jid=captured['jid'];cold=CombatService(ROOT,tmp_path)
    state=cold.journey_resume(jid,cold.journey_state(jid)['revision'])
    saved=next(iter(state['actors'][FOE]['source_states'][PARENT]['wards'].values()))
    remaining=Fraction(saved['remaining_num'],saved['remaining_den'])
    assert not saved.get('ended') and 0 < remaining < 60
    def diagnose(service,revision):
        option=next(o for o in service.journey_menu(jid,OWNER)['options'] if o['id']=='mantis_eye:'+FOE)
        state=service.journey_act(jid,revision,OWNER,option['kind'],option['payload'])
        return state,service.journey_menu(jid,OWNER)['properties']['mantis_private_diagnosis']['profile']
    # The still-live ward the snapshot omitted still conceals current HP.
    assert state['actors'][OWNER]['resources'][STAMINA]==97
    state,profile=diagnose(cold,state['revision'])
    assert state['actors'][OWNER]['resources'][STAMINA]==94
    assert profile['current_hp']=='concealed'
    assert 'mantis_private_diagnosis' not in cold.journey_menu(jid,FOE)['properties']
    # A cold service reads the same committed journey state.
    assert CombatService(ROOT,tmp_path).journey_menu(jid,OWNER)['properties']['mantis_private_diagnosis']['profile']['current_hp']=='concealed'
    # Once the ward actually ends, the real reading is available again.
    state=cold.journey_act(jid,state['revision'],OWNER,'wait',{'seconds':ceil(remaining)+1})
    state,profile=diagnose(cold,state['revision'])
    assert profile['current_hp']==1000
    assert state['actors'][OWNER]['resources'][STAMINA]==91


def test_next_journey_recompiles_only_the_creature_that_learned_the_school(tmp_path):
    """The continuation seam: a persisted acquisition rebuilds the real learned build."""
    captured={}
    def keep(combat,state):
        captured['combat'],captured['jid']=combat,state['journey_id']
        return state
    combat,table,mid=native(tmp_path,before_acquire=keep)
    rebuilt=combat._continued_bundles(combat.journeys.load(captured['jid']))
    assert set(rebuilt)=={OWNER},'a creature that learned nothing keeps its ordinary compile'
    assert any(a.get('display_name')=='Eye of the Mantis' for a in rebuilt[OWNER]['action_catalog'])



def test_pincer_replaces_a_strike_after_the_native_grapple_in_the_same_attack_action(tmp_path):
    combat,table,mid=native(tmp_path)
    prompts=settle(table,mid,candidate(combat,mid,'Grapple (Rapid Pincer)',target=FOE).candidate_id,
        picks={**DECLINE,'choice:needle.pincer_replace':'3','choice:needle.pincer_target':FOE,
            'choice:needle.save_choice':'STR'})
    engine=reload(tmp_path,mid)
    attacks=[e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER]
    assert len(attacks)==4
    assert any(c.condition_id.endswith('.grappled') and c.source_actor_id==OWNER
               for c in engine.state.actors[FOE].conditions.values())
    replacement=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.pincer_replace')
    assert len(replacement['choice']['options'])==3
    assert not any(action.parameters.get('rapid_pincer') for c in engine.legal_candidates()
                   if (action:=engine.action_catalog.get(c.source_definition_id)) is not None)
    settle(table,mid,candidate(combat,mid,'Joint Lock',target=FOE).candidate_id)
    assert any(c.condition_id.endswith('.restrained') for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())


def test_pincer_variants_keep_every_legal_unarmed_attack_option(tmp_path):
    """Rapid Pincer replaces one strike; it must not remove the option itself."""
    combat,table,mid=native(tmp_path)
    engine=combat._load_session(mid).engine
    offered={c.display_name for c in engine.legal_candidates()}
    ordinary={a.display_name for a in engine.action_catalog.values()
              if a.display_name in offered and not (a.parameters or {}).get('rapid_pincer')
              and (a.parameters or {}).get('typed',{}).get('attack_action')
              and any(isinstance(e,dict) and e.get('attack_kind')=='unarmed'
                      for e in a.parameters['typed'].get('effects') or [])}
    assert ordinary=={'Grapple','Iron Fist attack','Shove: Prone','Shove: Push 5 ft'}
    for name in sorted(ordinary):
        assert name+' (Rapid Pincer)' in offered,name
    grapple=next(a for a in engine.action_catalog.values() if a.display_name=='Grapple (Rapid Pincer)')
    save=next(e for e in grapple.parameters['typed']['effects'] if e.get('type')=='save')
    assert save['target_choice'] is True and grapple.parameters['rapid_pincer'] is True


def test_compound_pincer_drop_uses_cultivation_dc_and_not_eye_grapple_save_mode(tmp_path):
    from tests.auto11_service_support import SWORD
    from combat.ext.scoundrel_riders import held_possessions
    combat,table,mid=native(tmp_path,foe_kit=SWORD,foe_saves={'STR':0,'DEX':10,'CON':0},owner_str_score=8,foe_hp=10000)
    settle(table,mid,candidate(combat,mid,'Eye of the Mantis',target=FOE).candidate_id)
    for _ in range(15):
        settle(table,mid,candidate(combat,mid,'Grapple (Rapid Pincer)',target=FOE).candidate_id,
            picks={**DECLINE,'choice:needle.pincer_target':FOE,'choice:needle.save_choice':'DEX',
                'choice:needle.path_hit.'+P+'death_of_a_thousand_cuts':'Drop a held object'})
        engine=reload(tmp_path,mid)
        if not held_possessions(engine,engine.state.actors[FOE]):break
        turn(table,mid,FOE);turn(table,mid,OWNER)
    assert not held_possessions(engine,engine.state.actors[FOE])
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==FOE]
    ordinary=next(e for e in saves if '.unarmed.grapple' in e.source_definition_id)
    drop=next(e for e in saves if e.source_definition_id==P+'death_of_a_thousand_cuts')
    assert ordinary.payload['dc']==11 and drop.payload['dc']==22
    rolls={r.roll_id:r for r in engine.rolls}
    assert rolls[ordinary.payload['roll_id']].mode=='DISADVANTAGE'
    assert rolls[drop.payload['roll_id']].mode=='NORMAL'


@pytest.mark.parametrize('size',['Medium','Huge'])
def test_hooks_light_is_one_activation_when_the_free_grapple_is_declined_or_illegal(tmp_path,size):
    combat,table,mid=native(tmp_path,foe_size=size)
    prompts=hit(combat,table,mid,picks={**DECLINE,'choice:needle.mantis_hooks_light':'light'})
    engine=reload(tmp_path,mid)
    assert len([p for p in prompts if p['context']['reaction_source_id']=='choice:needle.mantis_hooks_light'])==1
    rolls=[r for r in engine.rolls if r.reason.startswith('DAMAGE:') and r.actor_id==OWNER]
    assert sum(not r.dice for r in rolls)==1
    assert engine.state.actors[OWNER].turn_flags['_round_mantis_hooks']
    assert not any(c.condition_id.endswith('.grappled') for c in engine.state.actors[FOE].conditions.values())



def test_pincer_can_be_chosen_when_a_later_normal_strike_is_actually_due(tmp_path):
    combat,table,mid=native(tmp_path)
    prompts=settle(table,mid,strike(combat,mid).candidate_id,picks={**DECLINE,
        'choice:needle.mantis_pincer_use':(None,None,'replace'),
        'choice:needle.pincer_target':(FOE,ALLY)})
    engine=reload(tmp_path,mid)
    attacks=[e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER]
    assert [e.target_ids for e in attacks]==[(FOE,),(FOE,),(FOE,),(ALLY,),(ALLY,)]
    uses=[p for p in prompts if p['context']['reaction_source_id']=='choice:needle.mantis_pincer_use']
    assert len(uses)==3
    assert engine.state.actors[OWNER].turn_flags['_round_rapid_pincer']
    assert engine.state.actors[OWNER].resources[STAMINA]==100


def test_declining_each_actual_pincer_checkpoint_preserves_four_strikes_and_the_use(tmp_path):
    combat,table,mid=native(tmp_path)
    prompts=settle(table,mid,strike(combat,mid).candidate_id,picks=DECLINE)
    engine=reload(tmp_path,mid)
    assert len([e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER])==4
    assert len([p for p in prompts if p['context']['reaction_source_id']=='choice:needle.mantis_pincer_use'])==4
    assert engine.state.actors[OWNER].turn_flags.get('_round_rapid_pincer') is None



def test_all_mantis_saves_use_cultivation_basis_not_recorded_technique_dc(tmp_path):
    from tests.auto11_service_support import SWORD
    from combat.save_dcs import save_dc
    combat,table,mid=native(tmp_path,foe_kit=SWORD)
    engine=reload(tmp_path,mid)
    assert save_dc(engine,engine.state.actors[OWNER],'save_dc')==100
    assert save_dc(engine,engine.state.actors[OWNER],'cultivation')==22
    hit(combat,table,mid,picks={**DECLINE,'choice:needle.mantis_hooks':'grapple',
        'choice:needle.path_hit.'+P+'death_of_a_thousand_cuts':'Drop a held object'})
    settle(table,mid,candidate(combat,mid,'Joint Lock',target=FOE).candidate_id)
    engine=reload(tmp_path,mid)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==FOE
           and any(name in e.source_definition_id for name in (P+'mantis_hooks',P+'joint_lock',P+'death_of_a_thousand_cuts'))]
    assert len(saves)==3 and all(e.payload['dc']==22 for e in saves)
    hold=next(c for c in engine.state.actors[FOE].conditions.values() if c.condition_id.endswith('.grappled'))
    assert hold.data['escape_dc']==22
    assert engine.state.actors[OWNER].resources[STAMINA]==95


def test_eye_first_grapple_attempt_is_separate_and_resets_on_the_next_turn(tmp_path):
    combat,table,mid=native(tmp_path,foe_saves={'STR':40,'DEX':40,'CON':0})
    settle(table,mid,candidate(combat,mid,'Eye of the Mantis',target=FOE).candidate_id)
    for repetition in range(2):
        for _ in range(5):
            before=combat._load_session(mid).engine.state.event_sequence
            settle(table,mid,candidate(combat,mid,'Grapple (Rapid Pincer)',target=FOE).candidate_id,
                picks={**DECLINE,'choice:needle.pincer_target':FOE,
                    'choice:needle.mantis_hooks':'grapple','choice:needle.save_choice':'DEX'})
            engine=reload(tmp_path,mid)
            saves=[e for e in engine.events if e.sequence>before and e.event_type=='SAVE_ROLLED'
                and e.actor_id==FOE and ('.unarmed.grapple' in e.source_definition_id
                    or e.source_definition_id==P+'mantis_hooks')]
            if len(saves)==2:break
            turn(table,mid,FOE);turn(table,mid,OWNER)
        assert len(saves)==2
        assert '.unarmed.grapple' in saves[0].source_definition_id
        assert saves[1].source_definition_id==P+'mantis_hooks'
        assert [e.payload['mode'] for e in saves]==['DISADVANTAGE','NORMAL']
        eye=next(c for c in engine.state.actors[FOE].conditions.values()
                 if c.condition_id=='condition:typed.eye_of_the_mantis')
        assert eye.data.get('grapple_turn') and eye.data.get('attack_turn')
        assert not eye.data.get('lock_turn')
        if repetition==0:
            turn(table,mid,FOE);turn(table,mid,OWNER)


def test_private_native_concealment_never_leaks_through_public_cards_or_past_history(tmp_path):
    marker='Mantis private ward sentinel'
    def declare(combat,state):
        fact=concealment_fact(expires=6)
        fact['value']['effect_source']=marker
        return admit_fact(combat,state,fact)
    combat,table,mid=native(tmp_path,before_acquire=declare)
    engine=reload(tmp_path,mid)
    assert any(c.condition_id=='condition:typed.mantis_diagnosis_concealment'
               for c in engine.state.actors[FOE].conditions.values())
    def private_public_views():
        public=json.dumps({'state':table.state(mid,include_menu=False),'events':table.events(mid,0)}).lower()
        assert marker.lower() not in public
        assert 'concealed from supernatural diagnosis' not in public
    private_public_views()
    settle(table,mid,candidate(combat,mid,'Eye of the Mantis',target=FOE).candidate_id)
    assert combat.observer_readings(mid,OWNER)[0]['details']['profile']['current_hp']=='concealed'
    private_public_views()
    for _ in range(4):
        settle(table,mid,table.state(mid)['menu']['end_turn'])
        engine=reload(tmp_path,mid)
        if not any(c.condition_id=='condition:typed.mantis_diagnosis_concealment'
                   for c in engine.state.actors[FOE].conditions.values()):break
    assert not any(c.condition_id=='condition:typed.mantis_diagnosis_concealment'
                   for c in engine.state.actors[FOE].conditions.values())
    assert engine.state.actors[OWNER].resources[STAMINA]==97
    private_public_views()
