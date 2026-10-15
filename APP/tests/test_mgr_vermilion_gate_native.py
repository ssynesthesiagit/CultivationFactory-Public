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


def game(tmp_path,cl=18,acquire=True,foe_at=None,foe_features=(),owner_dc=50,path_level=None,start_combat=True,effective_cl=None):
    s=CombatService(ROOT,tmp_path)
    docs={pid:sheet(['tianxia.path.body_refining.feature.iron_fist',*(foe_features if pid=='traveller' else [])],cl=cl,primary='Stamina',dc=owner_dc if pid=='guardian' else 16,name=name,score=20 if pid=='guardian' else 14)
          for pid,name in [('guardian','Wren'),('traveller','Mara'),('companion','Tobin')]}
    for pid,doc in docs.items():
        doc['identity']['path']='Body Refining'
        doc.setdefault('path_and_subpath',{}).update(path_record_id='tianxia.path.body_refining',path_record_ids=['tianxia.path.body_refining'],
            paths=[{'path_id':'tianxia.path.body_refining','attainment':cl if path_level is None else path_level}])
        if effective_cl is not None and pid=='guardian':doc['path_and_subpath']['paths'][0]['effective_cl']=effective_cl
        doc['ability_scores_and_statistics']['hit_points']['maximum']=300
        directory=s.combatant_library.install_root/pid;directory.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(directory/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    from combat.tabletop import to_battlefield
    saved=s.tabletop_maps.save({'map_id':'gate-courtyard','display_name':'Gate courtyard','width_squares':24,'height_squares':20,'starts':{'team1':[[3,6],[3,5]],'team2':[[6,6]]},'objects':[]})
    arena_id=to_battlefield(saved)['stable_id']
    positions={A:{'x':3,'y':6},B:foe_at or {'x':6,'y':6},C:{'x':3,'y':5}}
    state=s.create_journey(project_ids=list(docs),arena_id=arena_id,positions=positions,base_paces={k:100 for k in positions},control_modes={k:'MANUAL' for k in positions})
    jid=state['journey_id']
    if acquire:
        assert s.journey_source_choices(jid,A,PARENT)['options'][0]['id']=='choose'
        state=s.journey_acquire_source(jid,state['revision'],A,PARENT,{'choice':'choose'})
        assert any(e['kind']=='SUBPATH_ACQUIRED' and e['actor_id']==A for e in state['events'])
        assert not any(x.startswith(PREFIX) for x in docs['guardian']['path_and_subpath']['path_feature_record_ids'])
    cold=CombatService(ROOT,tmp_path);assert cold.journey_state(jid)==state
    if not start_combat:return cold,None,None,jid
    mid=cold.journey_start_combat(jid,state['revision'],{A:'team:a',C:'team:a',B:'team:b'},maximum_rounds=20)['match_id']
    table=TabletopService(cold,tmp_path)
    turn(table,mid,B);turn(table,mid,A);turn(table,mid,B)
    return cold,table,mid,jid


def move(combat,table,mid,actor,x,y,picks=None):
    turn(table,mid,actor)
    rows=[c for c in combat._load_session(mid).engine.legal_candidates() if c.kind=='MOVE' and c.destination and (c.destination.x,c.destination.y)==(x,y)]
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
    if offered:
        assert {o['id'] for o in offered[0]['choice']['options']}=={'prone','mark','force','push'}
        if choice=='prone':assert any(c.condition_id.endswith('prone') for c in engine.state.actors[B].conditions.values())
        if choice=='mark':assert any(c.condition_id.endswith('gate_marked') for c in engine.state.actors[B].conditions.values())


def test_closed_gate_cost_anchors_stationary_and_consent(tmp_path):
    combat,table,mid,_=game(tmp_path);turn(table,mid,A)
    before=reload(tmp_path,mid).state.actors[A].resources[STAMINA]
    prompts=commit(table,mid,candidate(combat,mid,"Heaven's Closed Gate").candidate_id)
    engine=reload(tmp_path,mid);owner=engine.state.actors[A];gate=owner.turn_flags['_round_closed_gate']
    assert owner.resources[STAMINA]==before-7 and gate['allies']==[C]
    assert any(p['context']['reaction_source_id'].startswith('choice:needle.fact_admission') for p in prompts)
    assert len(gate['posts'])==4 and gate['source_cl']==18
    for pid in gate['posts']:
        post=engine.state.objects[pid]
        assert post.ac==50 and post.current_hp==54 and post.component['harvestable'] is False
    move(combat,table,mid,A,2,6)
    assert reload(tmp_path,mid).state.actors[A].turn_flags['_round_closed_gate']['x']==3


def test_wrong_owner_is_inert(tmp_path):
    combat,table,mid,_=game(tmp_path,acquire=False);engine=reload(tmp_path,mid)
    assert not any(a.turn_flags.get('_round_gate_thresholds') for a in engine.state.actors.values())
    assert not any(a.display_name=="Heaven's Closed Gate" for a in engine.action_catalog.values())


def test_worlds_native_fold_step_one_check_and_failed_cost(tmp_path):
    combat,table,mid,_=game(tmp_path,foe_at={'x':5,'y':6},foe_features=['TAL_SPACE_FOLD_STEP'])
    engine=reload(tmp_path,mid);before=engine.state.actors[B].resources[STAMINA]
    first=len(engine.events)
    commit(table,mid,candidate(combat,mid,'Fold Step',at=(2,6)).candidate_id)
    engine=reload(tmp_path,mid)
    checks=[e for e in engine.events[first:] if e.event_type=='CHECK_ROLLED' and e.source_definition_id==PREFIX+'threshold_between_worlds']
    assert len(checks)==1 and checks[0].payload['success'] is False
    assert engine.state.actors[B].position.x==5
    assert engine.state.actors[B].resources[STAMINA]==before-1
    assert engine.state.actors[A].reaction_available


def test_shelter_native_shove_consent_reduction_and_cost(tmp_path):
    combat,table,mid,_=game(tmp_path,cl=6,foe_at={'x':2,'y':5})
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


def test_native_scene_gate_uses_real_seconds_and_scene_authority(tmp_path):
    combat,_,_,jid=game(tmp_path,start_combat=False)
    state=combat.journey_state(jid);before=state['actors'][A]['resources'][STAMINA]
    state=combat.journey_act(jid,state['revision'],C,'declare_fact',{'source':PARENT,'subject':C,'kind':'gate_crossing','scope':A,'value':1,'expires_at':60,'readers':[A]})
    state=combat.journey_act(jid,state['revision'],A,'gate_activate',{'allies':[C]})
    assert state['actors'][A]['resources'][STAMINA]==before-7
    source=state['actors'][A]['source_states'][PARENT];gate=json.loads(source['gate'])
    assert len(gate['posts'])==4 and gate['allies']==[C] and gate['expires_at']==60
    assert all(not state['runtime_objects'][pid]['destroyed'] for pid in gate['posts'])
    state=combat.journey_act(jid,state['revision'],A,'wait',{'seconds':59})
    assert 'gate' in state['actors'][A]['source_states'][PARENT]
    state=combat.journey_act(jid,state['revision'],A,'wait',{'seconds':1})
    assert 'gate' not in state['actors'][A]['source_states'][PARENT]
    assert all(state['runtime_objects'][pid]['destroyed'] for pid in gate['posts'])
    with pytest.raises(ValueError):combat.journey_act(jid,state['revision'],A,'gate_activate',{'allies':[]})
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state
    state=combat.journey_end_scene(jid,state['revision'],'The courtyard defense has ended.')
    assert state['events'][-1]['kind']=='SCENE_ENDED'
    state=combat.journey_act(jid,state['revision'],A,'gate_activate',{'allies':[]})
    assert state['actors'][A]['resources'][STAMINA]==before-14


def test_scene_gate_continues_into_native_combat_without_refund(tmp_path):
    combat,_,_,jid=game(tmp_path,start_combat=False)
    state=combat.journey_state(jid)
    state=combat.journey_act(jid,state['revision'],A,'gate_activate',{'allies':[]})
    before=state['actors'][A]['resources'][STAMINA]
    mid=combat.journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b',C:'team:a'})['match_id']
    engine=reload(tmp_path,mid)
    assert engine.state.actors[A].resources[STAMINA]==before
    gate=engine.state.actors[A].turn_flags['_round_closed_gate']
    assert len(gate['posts'])==4 and all(pid in engine.state.objects for pid in gate['posts'])


def test_effective_body_path_level_suppresses_higher_earned_rows(tmp_path):
    combat,table,mid,_=game(tmp_path,cl=18,effective_cl=3)
    engine=reload(tmp_path,mid)
    assert len(engine.state.actors[A].turn_flags['_round_gate_thresholds'])==1
    assert engine.state.actors[A].turn_flags['_round_gate_threshold_profile']['source_cl']==3
    assert not any(engine.action_catalog.get(c.source_definition_id) and engine.action_catalog[c.source_definition_id].display_name=="Heaven's Closed Gate" for c in engine.legal_candidates())
