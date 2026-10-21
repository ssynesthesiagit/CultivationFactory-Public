"""Native acquired Vermilion Gate continuation and shared-contract checks."""
import json
import pytest
from tests.test_mgr_vermilion_gate_native import (
    game,commit,turn,move,A,B,C,PARENT,PREFIX,STAMINA,ROOT,candidate,reload,act,
    CombatService,TabletopService,stable_native_journey_identity,
)


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


def test_native_scene_gate_uses_real_seconds_and_scene_authority(tmp_path):
    combat,_,_,jid=game(tmp_path,start_combat=False)
    state=combat.journey_state(jid);before=state['actors'][A]['resources'][STAMINA]
    state=combat.journey_act(jid,state['revision'],C,'declare_fact',{'source':PARENT,'subject':C,'kind':'gate_crossing','scope':A,'value':1,'expires_at':60,'readers':[A]})
    choice=next(o for o in combat.journey_menu(jid,A)['options'] if o['kind']=='gate_choose_ally' and o['payload']['ally']==C)
    state=combat.journey_act(jid,state['revision'],A,choice['kind'],choice['payload'])
    choice=next(o for o in combat.journey_menu(jid,A)['options'] if o['kind']=='gate_activate')
    assert choice['payload']['allies']==[C]
    state=combat.journey_act(jid,state['revision'],A,choice['kind'],choice['payload'])
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


def test_closed_gate_native_boundary_save_is_mover_choice_and_stops_before_entry(tmp_path):
    combat,table,mid,_=game(tmp_path,foe_at={'x':10,'y':6})
    turn(table,mid,A);commit(table,mid,candidate(combat,mid,"Heaven's Closed Gate").candidate_id)
    turn(table,mid,B);before=reload(tmp_path,mid).state.actors[B].current_hp
    prompts=move(combat,table,mid,B,8,6,{'choice:needle.closed_gate_save':['cha']})
    engine=reload(tmp_path,mid)
    choice=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.closed_gate_save')
    assert {o['id'] for o in choice['choice']['options']}=={'str','cha'}
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==B]
    assert saves and saves[-1].payload['reason'].endswith(':CHA')
    assert engine.state.actors[B].position.x==10 and engine._effective_speed(engine.state.actors[B])==0
    from combat.ext.ability_source import mechanic_at
    damage=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and B in e.target_ids and (mechanic_at(engine,e.source_definition_id) or e.source_definition_id)==PREFIX+'heaven_s_closed_gate']
    assert damage and 4<=before-engine.state.actors[B].current_hp<=32


def test_closed_gate_native_cover_sensitive_dexterity_save(tmp_path):
    combat,table,mid,_=game(tmp_path,foe_at={'x':10,'y':6},foe_features=['FIRE_TAL_INCINERATING_LANCE'])
    turn(table,mid,A);commit(table,mid,candidate(combat,mid,"Heaven's Closed Gate").candidate_id)
    turn(table,mid,B);first=len(reload(tmp_path,mid).events)
    commit(table,mid,candidate(combat,mid,'Incinerating Lance',at=(3,6)).candidate_id)
    engine=reload(tmp_path,mid)
    saves=[e for e in engine.events[first:] if e.event_type=='SAVE_ROLLED' and e.actor_id==A]
    assert saves and saves[-1].payload['save_bonus_contributions']['cover']==5


def test_closed_gate_success_crosses_with_one_extra_step_cost(tmp_path):
    combat,table,mid,_=game(tmp_path,foe_at={'x':10,'y':6},owner_dc=2)
    turn(table,mid,A);commit(table,mid,candidate(combat,mid,"Heaven's Closed Gate").candidate_id)
    turn(table,mid,B);engine=reload(tmp_path,mid);before=engine.state.actors[B].movement_remaining_ft;first=len(engine.events)
    move(combat,table,mid,B,8,6)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[B].position.x==8
    assert engine.state.actors[B].movement_remaining_ft==before-15
    moves=[e for e in engine.events[first:] if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==B and not e.payload.get('placed')]
    assert moves[-1].payload['cost_ft']==15
    assert len([e for e in engine.events[first:] if e.event_type=='SAVE_ROLLED' and e.actor_id==B])==1
    assert not any(z.active and z.trigger_profile.get('gate_crossing_actor')==B for z in engine.state.zones.values())
    assert not any(e.event_type=='DAMAGE_COMMITTED' and e.source_definition_id==PREFIX+'heaven_s_closed_gate' for e in engine.events)


def test_closed_gate_four_native_anchor_destructions_end_complete_gate(tmp_path):
    combat,table,mid,_=game(tmp_path,foe_at={'x':10,'y':6},owner_dc=2,foe_score=20,
        foe_features=['TAL_SOUND_BELL_THAT_BREAKS_THE_FORMATION'])
    turn(table,mid,A);commit(table,mid,candidate(combat,mid,"Heaven's Closed Gate").candidate_id)
    turn(table,mid,B);engine=reload(tmp_path,mid)
    posts=engine.state.actors[A].turn_flags['_round_closed_gate']['posts']
    owner_hp=engine.state.actors[A].current_hp
    for index,pid in enumerate(posts):
        for attempt in range(3):
            turn(table,mid,B)
            commit(table,mid,candidate(combat,mid,'Bell That Breaks the Formation',target=pid).candidate_id)
            engine=reload(tmp_path,mid)
            assert engine.state.actors[A].current_hp==owner_hp
            if engine.state.objects[pid].destroyed:break
            commit(table,mid,table.state(mid)['menu']['end_turn'])
        assert engine.state.objects[pid].destroyed
        assert all(not engine.state.objects[other].destroyed for other in posts[index+1:])
        if index<3:
            assert '_round_closed_gate' in engine.state.actors[A].turn_flags
            commit(table,mid,table.state(mid)['menu']['end_turn'])
    assert '_round_closed_gate' not in engine.state.actors[A].turn_flags
    assert engine.state.actors[A].current_hp==owner_hp
    assert not any(e.event_type=='DAMAGE_COMMITTED' and A in e.target_ids for e in engine.events)


def test_two_destroyed_native_posts_reduce_ranged_cover_without_stacking(tmp_path):
    combat,table,mid,_=game(tmp_path,foe_at={'x':10,'y':6},owner_dc=2,foe_score=20,
        foe_features=['TAL_SOUND_BELL_THAT_BREAKS_THE_FORMATION','TAL_SPACE_SPATIAL_EDGE'])
    turn(table,mid,A);commit(table,mid,candidate(combat,mid,"Heaven's Closed Gate").candidate_id)
    turn(table,mid,B)
    first=len(reload(tmp_path,mid).events)
    commit(table,mid,candidate(combat,mid,'Spatial Edge',target=A).candidate_id)
    engine=reload(tmp_path,mid)
    assert next(e for e in engine.events[first:] if e.event_type=='ATTACK_ROLLED' and e.actor_id==B).payload['cover_bonus']==5
    posts=engine.state.actors[A].turn_flags['_round_closed_gate']['posts']
    commit(table,mid,table.state(mid)['menu']['end_turn'])
    for pid in posts[:2]:
        for _ in range(3):
            turn(table,mid,B)
            commit(table,mid,candidate(combat,mid,'Bell That Breaks the Formation',target=pid).candidate_id)
            engine=reload(tmp_path,mid)
            commit(table,mid,table.state(mid)['menu']['end_turn'])
            if engine.state.objects[pid].destroyed:break
        assert engine.state.objects[pid].destroyed
    turn(table,mid,B);first=len(reload(tmp_path,mid).events)
    commit(table,mid,candidate(combat,mid,'Spatial Edge',target=A).candidate_id)
    engine=reload(tmp_path,mid)
    assert '_round_closed_gate' in engine.state.actors[A].turn_flags
    assert sum(engine.state.objects[p].destroyed for p in posts)==2
    assert next(e for e in engine.events[first:] if e.event_type=='ATTACK_ROLLED' and e.actor_id==B).payload['cover_bonus']==2
