"""Native acquisition -> journey combat -> table commit -> cold replay."""
import json
import zipfile
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT,sheet
from tests.worker2_support import candidate,reload
from tests.test_r9i_karma_persistence import act
PARENT='tianxia.subpath.body.vermilion_gate_guardian_body'
PREFIX=PARENT+'.feature.'
A='actor:factory.guardian';B='actor:factory.traveller';C='actor:factory.companion'
STAMINA='resource:core.stamina'
PICKS={'choice:needle.threshold_first':['cell:4,5'],'choice:needle.threshold_last':['cell:4,7'],
       'choice:needle.twin_guardian_posts':['prone'],'choice:needle.closed_gate_save':['str']}


@pytest.fixture(autouse=True)
def stable_native_journey_identity(monkeypatch):
    # Deterministic identity transport keeps the native seeded roller repeatable.
    # It grants no source or mechanical outcome.
    monkeypatch.setattr('combat.journey.secrets.token_hex',lambda n:'c'*24)


def commit(table,mid,cid,picks=None):
    answers=[];prompts=[]
    for _ in range(60):
        result=act(table,mid,cid,answers)
        if result['status']!='REACTION_REQUIRED':
            assert result['status']=='COMMITTED',result
            return prompts
        p=result['reaction'];prompts.append(p);rid=p['context']['reaction_source_id']
        choice=(picks or {}).get(rid,PICKS.get(rid,'first' if rid.startswith('choice:') else None))
        answer={**p['context'],'selection':'USE' if choice is not None else 'DECLINE'}
        if choice is not None and p.get('choice'):
            answer['option_ids']=[p['choice']['options'][0]['id']] if choice=='first' else choice
        answers.append(answer)
    raise AssertionError('Too many questions')


def turn(table,mid,actor,picks=None):
    for _ in range(15):
        state=table.state(mid)
        if state['menu']['actor_id']==actor:return
        commit(table,mid,state['menu']['end_turn'],picks)
    raise AssertionError('No turn')


def game(tmp_path,cl=18,acquire=True,foe_at=None,foe_features=(),owner_dc=50,path_level=None,start_combat=True,effective_cl=None,foe_dc=16,foe_cl=None,ally_at=None,owner_score=20,foe_score=14,ally_features=(),owner_project_id="guardian",owner_at=None,initial_picks=None):
    owner_id="actor:factory."+owner_project_id
    s=CombatService(ROOT,tmp_path)
    docs={pid:sheet(['tianxia.path.body_refining.feature.iron_fist',*(['tianxia.path.body_refining.feature.extra_attack'] if pid=='guardian' and (cl if path_level is None else path_level)>=5 else []),*(foe_features if pid=='traveller' else ally_features if pid=='companion' else [])],cl=foe_cl if pid=='traveller' and foe_cl is not None else cl,primary='Stamina',dc=owner_dc if pid=='guardian' else foe_dc,name=name,score=owner_score if pid=='guardian' else foe_score if pid=='traveller' else 14)
          for pid,name in [('guardian','Wren'),('traveller','Mara'),('companion','Tobin')]}
    for pid,doc in docs.items():
        doc['identity']['path']='Body Refining'
        doc.setdefault('path_and_subpath',{}).update(path_record_id='tianxia.path.body_refining',path_record_ids=['tianxia.path.body_refining'],
            paths=[{'path_id':'tianxia.path.body_refining','effective_cl':foe_cl if pid=='traveller' and foe_cl is not None else cl if path_level is None else path_level}])
        if effective_cl is not None and pid=='guardian':doc['path_and_subpath']['paths'][0].update(attainment=cl,effective_cl=effective_cl)
        doc['ability_scores_and_statistics']['hit_points']['maximum']=300
        # The installed Body build's derived maximum, rather than a test-only pool.
        doc['ability_scores_and_statistics']['primary_resource']['maximum']=(foe_cl if pid=='traveller' and foe_cl is not None else cl if path_level is None else path_level)*((owner_score-10)//2 if pid=='guardian' else (foe_score-10)//2 if pid=='traveller' else 2)
        directory=s.combatant_library.install_root/(owner_project_id if pid=="guardian" else pid);directory.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(directory/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    from combat.tabletop import to_battlefield
    saved=s.tabletop_maps.save({'map_id':'gate-courtyard','display_name':'Gate courtyard','width_squares':24,'height_squares':20,'starts':{'team1':[[3,6],[3,5]],'team2':[[6,6]]},'objects':[]})
    arena_id=to_battlefield(saved)['stable_id']
    positions={owner_id:owner_at or {'x':3,'y':6},B:foe_at or {'x':6,'y':6},C:ally_at or {'x':3,'y':5}}
    state=s.create_journey(project_ids=[owner_project_id,"traveller","companion"],arena_id=arena_id,positions=positions,base_paces={k:100 for k in positions},control_modes={k:'MANUAL' for k in positions})
    jid=state['journey_id']
    if acquire:
        assert s.journey_source_choices(jid,owner_id,PARENT)['options'][0]['id']=='choose'
        state=s.journey_acquire_source(jid,state['revision'],owner_id,PARENT,{'choice':'choose'})
        assert any(e['kind']=='SUBPATH_ACQUIRED' and e['actor_id']==owner_id for e in state['events'])
        assert not any(x.startswith(PREFIX) for x in docs['guardian']['path_and_subpath']['path_feature_record_ids'])
    cold=CombatService(ROOT,tmp_path);assert cold.journey_state(jid)==state
    if not start_combat:return cold,None,None,jid
    mid=cold.journey_start_combat(jid,state['revision'],{owner_id:'team:a',C:'team:a',B:'team:b'},maximum_rounds=20)['match_id']
    table=TabletopService(cold,tmp_path)
    turn(table,mid,B,initial_picks);turn(table,mid,owner_id,initial_picks);turn(table,mid,B,initial_picks)
    return cold,table,mid,jid


def move(combat,table,mid,actor,x,y,picks=None):
    turn(table,mid,actor)
    engine=combat._load_session(mid).engine
    rows=[c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination and (c.destination.x,c.destination.y)==(x,y)
        and c.destination.z==engine.state.actors[actor].position.z
        and c.metadata.get('movement_mode','walk')=='walk']
    assert rows,(actor,x,y)
    return commit(table,mid,rows[0].candidate_id,picks)


def test_acquisition_and_endpoint_placement_survive_cold_replay(tmp_path):
    combat,table,mid,jid=game(tmp_path)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[A].turn_flags['_round_gate_thresholds']==[[4,5,4,7],[4,5,4,7]]
    assert len([z for z in engine.state.zones.values() if z.active and z.owner_id==A])==2
    assert combat.journey_state(jid)['actors'][A]['source_states'][PARENT]['source_cl']==18


def test_guardian_attack_precedes_crossing(tmp_path):
    combat,table,mid,_=game(tmp_path,cl=3,foe_at={'x':5,'y':6})
    prompts=move(combat,table,mid,B,3,7)
    engine=reload(tmp_path,mid);foe=engine.state.actors[B]
    assert any(p['context']['reaction_source_id']=='choice:needle.guardian_at_the_gate' for p in prompts)
    rolled=[e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==A]
    assert len(rolled)==1
    offer=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.guardian_at_the_gate')
    assert not any('Improvised' in o.get('label','') for o in offer['choice']['options'])
    native_moves=[e for e in engine.events if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==B and not e.payload.get('placed')]
    assert native_moves and rolled[0].sequence<native_moves[-1].sequence
    if rolled[-1].payload.get('provisional_hit'):
        assert foe.position.x>=4 and engine._effective_speed(foe)==0
        assert any(c.condition_id.endswith('reaction_denied') for c in foe.conditions.values())
    else:assert foe.position.x==3
    assert not engine.state.actors[A].reaction_available


@pytest.mark.parametrize('choice',['prone','mark','force','push'])
def test_twin_each_result_reachable(tmp_path,choice):
    combat,table,mid,_=game(tmp_path,cl=10,foe_at={'x':5,'y':6})
    prompts=move(combat,table,mid,B,3,7,{'choice:needle.twin_guardian_posts':[choice]})
    engine=reload(tmp_path,mid)
    offered=[p for p in prompts if p['context']['reaction_source_id']=='choice:needle.twin_guardian_posts']
    assert offered, 'A confirmed Guardian hit must offer every Twin result'
    assert len([e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==A])==1
    if offered:
        assert {o['id'] for o in offered[0]['choice']['options']}=={'prone','mark','force','push'}
        if choice=='prone':assert any(c.condition_id.endswith('prone') for c in engine.state.actors[B].conditions.values())
        if choice=='mark':assert any(c.condition_id.endswith('gate_marked') for c in engine.state.actors[B].conditions.values())
        if choice=='push':assert engine.state.actors[B].position.x==6
        if choice=='force':
            packets=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.actor_id==A and B in e.target_ids]
            assert {e.payload['damage_type'] for e in packets}=={'FORCE','BLUDGEONING'}
            assert sum(e.payload['hp_damage'] for e in packets)==300-engine.state.actors[B].current_hp
            assert any(e.event_type=='DAMAGE_ROLLED' and e.actor_id==A and e.payload['expression']=='2d8+0' for e in engine.events)




def test_wrong_owner_is_inert(tmp_path):
    combat,table,mid,_=game(tmp_path,acquire=False);engine=reload(tmp_path,mid)
    assert not any(a.turn_flags.get('_round_gate_thresholds') for a in engine.state.actors.values())
    assert not any(a.display_name=="Heaven's Closed Gate" for a in engine.action_catalog.values())


def test_worlds_native_fold_step_one_check_and_failed_cost(tmp_path):
    combat,table,mid,_=game(tmp_path,foe_at={'x':5,'y':6},foe_features=['TAL_SPACE_FOLD_STEP'])
    engine=reload(tmp_path,mid);before=engine.state.actors[B].resources[STAMINA]
    first=len(engine.events)
    commit(table,mid,candidate(combat,mid,'Fold Step',at=(2,6)).candidate_id,{'choice:needle.teleport_destination':['cell:2,6']})
    engine=reload(tmp_path,mid)
    checks=[e for e in engine.events[first:] if e.event_type=='CHECK_ROLLED' and e.source_definition_id==PREFIX+'threshold_between_worlds']
    assert len(checks)==1 and checks[0].payload['success'] is False
    assert engine.state.actors[B].position.x==5
    assert engine.state.actors[B].resources[STAMINA]==before-1
    assert engine.state.actors[A].reaction_available


def test_shelter_native_shove_consent_reduction_and_cost(tmp_path):
    combat,table,mid,_=game(tmp_path,cl=6,foe_at={'x':2,'y':5},foe_dc=50,foe_score=20)
    before=reload(tmp_path,mid).state.actors[A].resources[STAMINA]
    prompts=commit(table,mid,candidate(combat,mid,'Shove: Push 5 ft',target=C).candidate_id)
    engine=reload(tmp_path,mid)
    receipts=[e for e in engine.events if e.event_type=='REACTION_RESOLVED' and e.source_definition_id==PREFIX+'shelter_behind_the_gate']
    assert receipts and receipts[-1].payload['distance_before']==5 and receipts[-1].payload['distance_after']==0
    assert any(p['context']['reaction_source_id'].startswith('choice:needle.fact_admission') for p in prompts)
    assert engine.state.actors[A].resources[STAMINA]==before-1
    assert not engine.state.actors[A].reaction_available


@pytest.mark.parametrize('guard',['duplicate','unknown','path_level'])
def test_acquisition_guards_are_atomic(tmp_path,guard):
    combat,_,_,jid=game(tmp_path,cl=18,path_level=2 if guard=='path_level' else 3,acquire=guard!='path_level',start_combat=False)
    state=combat.journey_state(jid)
    if guard!='path_level':
        acquired=json.loads(state['actors'][A]['source_states'][PARENT]['acquired_sheet'])
        assert [x for x in acquired['path_and_subpath']['path_feature_record_ids'] if x.startswith(PREFIX)]==[PREFIX+'guardian_at_the_gate']
    with pytest.raises(ValueError):combat.journey_acquire_source(jid,state['revision'],A,'unknown' if guard=='unknown' else PARENT,{'choice':'choose'})
    assert combat.journey_state(jid)==state






def test_effective_body_path_level_suppresses_higher_earned_rows(tmp_path):
    combat,table,mid,_=game(tmp_path,cl=18,effective_cl=3)
    engine=reload(tmp_path,mid)
    assert len(engine.state.actors[A].turn_flags['_round_gate_thresholds'])==1
    assert engine.state.actors[A].turn_flags['_round_gate_threshold_profile']['source_cl']==3
    assert not any(engine.action_catalog.get(c.source_definition_id) and engine.action_catalog[c.source_definition_id].display_name=="Heaven's Closed Gate" for c in engine.legal_candidates())


def test_shelter_chosen_ac_adds_to_worlds_cover_for_one_native_ranged_attack(tmp_path):
    combat,table,mid,_=game(tmp_path,cl=14,foe_at={'x':5,'y':6},foe_features=['TAL_SPACE_SPATIAL_EDGE'])
    engine=reload(tmp_path,mid);before=len(engine.events)
    prompts=commit(table,mid,candidate(combat,mid,'Spatial Edge',target=C).candidate_id)
    engine=reload(tmp_path,mid)
    attacks=[e for e in engine.events[before:] if e.event_type=='ATTACK_ROLLED' and e.actor_id==B]
    assert len(attacks)==1 and attacks[0].payload['cover_bonus']==2
    assert attacks[0].payload['target_ac']==17
    assert any('shelter_' in p['context']['reaction_source_id'] for p in prompts)
    assert not any(m.source_definition_id==PREFIX+'shelter_behind_the_gate' for m in engine.state.actors[C].modifiers.values())
    assert engine.state.actors[A].reaction_available






def test_guardian_can_decline_without_spending_reaction(tmp_path):
    combat,table,mid,_=game(tmp_path,cl=3,foe_at={'x':5,'y':6})
    prompts=move(combat,table,mid,B,3,7,{'choice:needle.guardian_at_the_gate':None})
    engine=reload(tmp_path,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.guardian_at_the_gate' for p in prompts)
    assert engine.state.actors[B].position.x==3 and engine.state.actors[A].reaction_available
    assert not any(e.event_type=='ATTACK_ROLLED' and e.actor_id==A for e in engine.events)


def test_shelter_recipient_can_refuse_before_payment(tmp_path):
    combat,table,mid,_=game(tmp_path,cl=6,foe_at={'x':2,'y':5},foe_dc=50,foe_score=20)
    before=reload(tmp_path,mid).state.actors[A].resources[STAMINA]
    # Consent IDs contain the declared source, not a fixture-supplied fact.
    answers=[];prompts=[];cid=candidate(combat,mid,'Shove: Push 5 ft',target=C).candidate_id
    for _ in range(60):
        result=act(table,mid,cid,answers)
        if result['status']=='COMMITTED':break
        assert result['status']=='REACTION_REQUIRED',result
        p=result['reaction'];prompts.append(p);rid=p['context']['reaction_source_id']
        answer={**p['context'],'selection':'DECLINE'}
        if rid.startswith('choice:') and not rid.startswith('choice:needle.fact_admission'):
            answer.update(selection='USE',option_ids=[p['choice']['options'][0]['id']])
        answers.append(answer)
    else:raise AssertionError('No commit')
    engine=reload(tmp_path,mid)
    assert any(p['context']['reaction_source_id'].startswith('choice:needle.fact_admission') for p in prompts)
    assert engine.state.actors[A].resources[STAMINA]==before and engine.state.actors[A].reaction_available
    assert not any(e.event_type=='REACTION_RESOLVED' and e.source_definition_id==PREFIX+'shelter_behind_the_gate' for e in engine.events)


def test_worlds_same_side_spatial_movement_has_no_threshold_check(tmp_path):
    combat,table,mid,_=game(tmp_path,cl=14,foe_at={'x':5,'y':6},foe_features=['TAL_SPACE_FOLD_STEP'])
    first=len(reload(tmp_path,mid).events)
    commit(table,mid,candidate(combat,mid,'Fold Step',at=(6,6)).candidate_id,{'choice:needle.teleport_destination':['cell:6,6']})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[B].position.x==6
    assert not any(e.event_type=='CHECK_ROLLED' and e.source_definition_id==PREFIX+'threshold_between_worlds' for e in engine.events[first:])




@pytest.mark.parametrize('target,mode',[(A,'NORMAL'),(C,'DISADVANTAGE')])
def test_twin_mark_changes_only_attacks_against_other_creatures(tmp_path,target,mode):
    combat,table,mid,_=game(tmp_path,cl=10,foe_at={'x':5,'y':6},ally_at={'x':5,'y':7})
    move(combat,table,mid,B,3,7,{'choice:needle.twin_guardian_posts':['mark']})
    assert any(c.condition_id.endswith('gate_marked') for c in reload(tmp_path,mid).state.actors[B].conditions.values())
    first=len(reload(tmp_path,mid).events)
    commit(table,mid,candidate(combat,mid,'Iron Fist attack',target=target).candidate_id)
    engine=reload(tmp_path,mid)
    rolls=[e for e in engine.events[first:] if e.event_type=='ATTACK_ROLLED' and e.actor_id==B]
    assert rolls and rolls[0].payload['mode']==mode




def test_shelter_cancels_only_same_native_stomp_movement_prone_rider(tmp_path):
    combat,table,mid,_=game(tmp_path,cl=18,foe_at={'x':2,'y':5},foe_dc=50,foe_cl=18,
        foe_features=['tianxia.subpath.body.flesh_crucible.feature.world_shaking_stomp'])
    engine=combat._load_session(mid).engine
    options=[c for c in engine.legal_candidates() if c.destination and (c.destination.x,c.destination.y)==(3,5)
        and getattr(engine.action_catalog.get(c.source_definition_id),'display_name','').startswith('World-Shaking Stomp')]
    assert options
    commit(table,mid,options[0].candidate_id)
    engine=reload(tmp_path,mid)
    receipts=[e for e in engine.events if e.event_type=='REACTION_RESOLVED' and e.source_definition_id==PREFIX+'shelter_behind_the_gate' and C in e.target_ids]
    assert receipts and receipts[-1].payload['distance_after']==0
    assert not any(c.condition_id.endswith('prone') for c in engine.state.actors[C].conditions.values())
    assert not any(e.event_type=='CONDITION_APPLIED' and C in e.target_ids and e.payload.get('condition_id','').endswith('prone') for e in engine.events)


@pytest.mark.parametrize('cl,checked',[(3,False),(14,True)])
def test_native_phase_step_uses_spatial_rule_without_guardian(tmp_path,cl,checked):
    combat,table,mid,_=game(tmp_path,cl=cl,foe_at={'x':5,'y':6},foe_features=['tianxia.talent.space.phase_step'])
    commit(table,mid,candidate(combat,mid,'Phase Step').candidate_id)
    first=len(reload(tmp_path,mid).events)
    prompts=move(combat,table,mid,B,3,7)
    engine=reload(tmp_path,mid)
    checks=[e for e in engine.events[first:] if e.event_type=='CHECK_ROLLED' and e.source_definition_id==PREFIX+'threshold_between_worlds']
    assert len(checks)==int(checked)
    assert not any(p['context']['reaction_source_id']=='choice:needle.guardian_at_the_gate' for p in prompts)
    assert engine.state.actors[A].reaction_available
    assert engine.state.actors[B].position.x==(5 if checked else 3)












def test_guardian_native_dodge_miss_allows_crossing(tmp_path):
    combat,table,mid,_=game(tmp_path,cl=3,foe_at={'x':5,'y':6})
    commit(table,mid,candidate(combat,mid,'Dodge').candidate_id)
    move(combat,table,mid,B,3,7)
    engine=reload(tmp_path,mid)
    rolls=[e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==A]
    assert len(rolls)==1 and rolls[0].payload['mode']=='DISADVANTAGE'
    assert rolls[0].payload['provisional_hit'] is False
    assert engine.state.actors[B].position.x==3 and engine._effective_speed(engine.state.actors[B])>0
    assert not any(c.condition_id.endswith('reaction_denied') for c in engine.state.actors[B].conditions.values())


def test_guardian_intercepts_native_forced_route_before_placement(tmp_path):
    combat,table,mid,_=game(tmp_path,cl=3,foe_at={'x':5,'y':7},ally_at={'x':6,'y':7},
        ally_features=['TAL_FORCE_SHOCKWAVE'],foe_dc=50)
    turn(table,mid,C);first=len(reload(tmp_path,mid).events)
    prompts=commit(table,mid,candidate(combat,mid,'Shockwave',at=(6,7),remote=False).candidate_id,
        {'choice:needle.area_recipients':[B]})
    engine=reload(tmp_path,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.guardian_at_the_gate' for p in prompts)
    attacks=[e for e in engine.events[first:] if e.event_type=='ATTACK_ROLLED' and e.actor_id==A]
    forced=[e for e in engine.events[first:] if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==B and e.payload.get('forced') and not e.payload.get('placed')]
    assert len(attacks)==1 and forced and attacks[0].sequence<forced[-1].sequence
    if attacks[0].payload['provisional_hit']:
        assert engine.state.actors[B].position.x>=4 and engine._effective_speed(engine.state.actors[B])==0
    assert not engine.state.actors[A].reaction_available


def test_shelter_reads_committed_marked_origin_not_caster_position(tmp_path):
    combat,table,mid,_=game(tmp_path,cl=14,foe_at={'x':5,'y':6},
        foe_features=['tianxia.talent.ink.marked_origin'])
    move(combat,table,mid,B,4,6)
    commit(table,mid,candidate(combat,mid,'Press Mark',target=A).candidate_id,
        {'choice:needle.ink_accept':['accept'],'choice:needle.ink_conceal':None})
    move(combat,table,mid,B,5,6)
    commit(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,B)
    first=len(reload(tmp_path,mid).events)
    engine=combat._load_session(mid).engine
    options=[c for c in engine.legal_candidates() if c.target_ids==(C,) and c.metadata.get('effect_origin',{}).get('id')=='ink:'+A
        and ((engine.action_catalog[c.source_definition_id].parameters or {}).get('typed') or {}).get('source')=='INK_BASE_INK_LASH']
    assert options,'The actual acquired Ink Mark must publish a Marked Origin attack option'
    prompts=commit(table,mid,options[0].candidate_id)
    engine=reload(tmp_path,mid)
    rolls=[e for e in engine.events[first:] if e.event_type=='ATTACK_ROLLED' and e.actor_id==B]
    assert len(rolls)==1 and rolls[0].payload['target_ac']==14 and rolls[0].payload['cover_bonus']==0
    assert not any(p['context']['reaction_source_id'].startswith('choice:needle.shelter_') for p in prompts)
    assert engine.state.actors[B].position.x==5


@pytest.mark.parametrize('cl,optional',[(3,False),(10,True)])
def test_base_threshold_is_required_but_twin_may_place_none(tmp_path,cl,optional):
    combat,table,mid,_=game(tmp_path,cl=cl)
    turn(table,mid,C)
    cid=table.state(mid)['menu']['end_turn']
    result=act(table,mid,cid)
    assert result['status']=='REACTION_REQUIRED',result
    prompt=result['reaction']
    assert prompt['context']['reaction_source_id']=='choice:needle.threshold_first'
    assert prompt['choice']['allow_decline'] is optional
    commit(table,mid,cid,{'choice:needle.threshold_first':None} if optional else {})
    engine=reload(tmp_path,mid)
    assert len(engine.state.actors[A].turn_flags['_round_gate_thresholds'])==(0 if optional else 1)


def test_shelter_does_not_reduce_movement_thirty_feet_above_ground_line(tmp_path,height=6,rescued=False):
    from combat.flight import profile
    incarnation='tianxia.subpath.body.kensei.feature.sword_saint_incarnation'
    combat,table,mid,_=game(tmp_path,foe_at={'x':2,'y':5},foe_dc=50,foe_score=20,
        foe_features=[incarnation],ally_features=[incarnation])
    # Let the ally rise before the enemy manifests its own reach aura. Both
    # creatures acquire flight through an actual printed Bonus Action.
    for actor in (C,B):
        turn(table,mid,actor)
        commit(table,mid,candidate(combat,mid,'Sword Saint Incarnation').candidate_id)
        engine=reload(tmp_path,mid)
        assert profile(engine,engine.state.actors[actor]).hover
        position=engine.state.actors[actor].position
        rows=[row for row in engine.legal_candidates() if row.kind=='MOVE' and row.destination
            and (row.destination.x,row.destination.y,row.destination.z)==(position.x,position.y,height)]
        assert rows
        commit(table,mid,rows[0].candidate_id)
        assert reload(tmp_path,mid).state.actors[actor].position.z==height
    before=reload(tmp_path,mid).state.actors[A].resources[STAMINA]
    cid=candidate(combat,mid,'Shove: Push 5 ft',target=C).candidate_id
    answers=[]
    for _ in range(60):
        result=act(table,mid,cid,answers)
        if result['status']=='COMMITTED':break
        assert result['status']=='REACTION_REQUIRED',result
        prompt=result['reaction'];answer={**prompt['context'],'selection':'USE'}
        if prompt.get('choice'):answer['option_ids']=[prompt['choice']['options'][0]['id']]
        answers.append(answer)
    else:raise AssertionError('The native shove must commit')
    engine=reload(tmp_path,mid)
    assert engine.state.actors[A].resources[STAMINA]==before-(1 if rescued else 0)
    assert engine.state.actors[C].position.z==(0 if rescued else height)
    receipts=[event for event in engine.events if event.event_type=='REACTION_RESOLVED'
        and event.source_definition_id==PREFIX+'shelter_behind_the_gate']
    assert bool(receipts) is rescued


def test_shelter_nearby_airborne_ally_lands_in_nearest_ground_space(tmp_path):
    test_shelter_does_not_reduce_movement_thirty_feet_above_ground_line(tmp_path,height=1,rescued=True)


def test_shelter_range_and_landing_use_actual_large_occupied_space(tmp_path):
    incarnation='tianxia.subpath.body.black_thorn_demon_body.feature.calamity_briar_incarnation'
    combat,table,mid,_=game(tmp_path,foe_at={'x':0,'y':7},foe_dc=50,foe_score=20,
        ally_at={'x':1,'y':7},ally_features=[incarnation])
    turn(table,mid,C)
    commit(table,mid,candidate(combat,mid,'Calamity Briar Incarnation').candidate_id)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[C].transformed_size_category=='Large'
    assert (2,7) in set(engine._actor_cells(engine.state.actors[C]))
    turn(table,mid,B)
    before=reload(tmp_path,mid).state.actors[A].resources[STAMINA]
    prompts=commit(table,mid,candidate(combat,mid,'Shove: Push 5 ft',target=C).candidate_id)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[A].resources[STAMINA]==before-1
    assert any(p['context']['reaction_source_id'].startswith('choice:needle.fact_admission') for p in prompts)
    assert any(e.event_type=='REACTION_RESOLVED' and e.source_definition_id==PREFIX+'shelter_behind_the_gate'
        and e.payload['distance_after']==0 for e in engine.events)
    assert (engine.state.actors[C].position.x,engine.state.actors[C].position.y)==(2,7)
    assert all(x<=4 for x,y in engine._actor_cells(engine.state.actors[C]))


def test_shelter_advantage_resists_crossing_by_large_occupied_space(tmp_path):
    incarnation='tianxia.subpath.body.black_thorn_demon_body.feature.calamity_briar_incarnation'
    combat,table,mid,_=game(tmp_path,foe_at={'x':2,'y':7},foe_dc=50,foe_score=20,
        ally_at={'x':3,'y':7},ally_features=[incarnation])
    turn(table,mid,C)
    commit(table,mid,candidate(combat,mid,'Calamity Briar Incarnation').candidate_id)
    assert reload(tmp_path,mid).state.actors[C].transformed_size_category=='Large'
    turn(table,mid,B)
    engine=reload(tmp_path,mid);first=len(engine.events);before=engine.state.actors[A].resources[STAMINA]
    commit(table,mid,candidate(combat,mid,'Shove: Push 5 ft',target=C).candidate_id,
        {'choice:needle.shelter_reaction':None})
    engine=reload(tmp_path,mid)
    checks=[event for event in engine.events[first:] if event.event_type in ('CHECK_ROLLED','SAVE_ROLLED') and event.actor_id==C]
    assert checks and checks[-1].payload['mode']=='ADVANTAGE'
    assert engine.state.actors[A].resources[STAMINA]==before


def test_twin_push_stops_at_map_edge_without_stationary_movement(tmp_path):
    picks={'choice:needle.threshold_first':['cell:1,5'],'choice:needle.threshold_last':['cell:1,7'],
        'choice:needle.twin_guardian_posts':['push']}
    combat,table,mid,_=game(tmp_path,cl=10,owner_at={'x':2,'y':6},foe_at={'x':0,'y':6},initial_picks=picks)
    assert reload(tmp_path,mid).state.actors[A].turn_flags['_round_gate_thresholds']==[[1,5,1,7],[1,5,1,7]]
    prompts=move(combat,table,mid,B,2,7,picks)
    engine=reload(tmp_path,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.twin_guardian_posts' for p in prompts)
    forced=[e for e in engine.events if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==B
        and e.payload.get('forced') and not e.payload.get('placed')]
    assert forced
    path=forced[-1].payload['path']
    assert all(a!=b for a,b in zip(path,path[1:]))
    assert forced[-1].payload['cost_ft']==5
    assert (engine.state.actors[B].position.x,engine.state.actors[B].position.y)==(0,7)


def test_shelter_does_not_grant_resistance_advantage_to_native_phasing(tmp_path):
    from combat.ext.space_phase import phased
    picks={'choice:needle.threshold_first':['cell:4,5'],'choice:needle.threshold_last':['cell:3,7'],
        'choice:needle.shelter_reaction':None}
    combat,table,mid,_=game(tmp_path,foe_at={'x':2,'y':4},foe_score=20,
        ally_features=['tianxia.talent.space.phase_step'],initial_picks=picks)
    turn(table,mid,C,picks)
    commit(table,mid,candidate(combat,mid,'Phase Step').candidate_id,picks)
    assert phased(reload(tmp_path,mid).state.actors[C])
    turn(table,mid,B,picks)
    first=len(reload(tmp_path,mid).events)
    commit(table,mid,candidate(combat,mid,'Shove: Push 5 ft',target=C).candidate_id,picks)
    engine=reload(tmp_path,mid)
    checks=[e for e in engine.events[first:] if e.event_type=='SAVE_ROLLED' and e.actor_id==C]
    assert checks and checks[-1].payload['mode']=='NORMAL'
