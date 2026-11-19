"""Printed Flowing River effects through table/service intent commit and cold replay."""
import pytest
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload as _reload, turn, cell_send
from combat.ext.flowing_second_pass import TEN, BETWEEN, RETALIATE, GUARD
P='TAL_FLOWING_RIVER_'
RESPONSE=P+'FLOWING_RESPONSE'
FOCUS='resource:core.martial_focus'


def reload(combat,mid):
    engine=_reload(combat,mid)
    assert combat._load_session(mid).verify()['status']=='PASS'
    return engine


def settle(send,picker=None):
    answers,prompts=[],[]
    for _ in range(25):
        result=send(answers)
        if result['status']!='REACTION_REQUIRED':
            assert result['status']=='COMMITTED',result
            return result,prompts
        p=result['reaction'];prompts.append(p)
        choice=p.get('choice')
        ids=picker(p) if picker else [o['id'] for o in (choice or {}).get('options',[])][:1]
        answers.append({**p['context'],'selection':'DECLINE' if choice and not ids else 'USE','option_ids':ids})
    raise AssertionError('too many questions')


def hard_attack(b):
    for a in b['action_catalog']:
        if a['display_name']=='Cause':
            a['parameters']['typed']['numbers']['attack_bonus']=100
            a['parameters']['typed']['range_ft']=30 if a['parameters']['typed']['effects'][0].get('attack_kind')=='ranged' else None


def decline_steps(prompt):
    cid=prompt['context']['reaction_source_id']
    if cid=='choice:needle.river_step': return []
    return [o['id'] for o in (prompt.get('choice') or {}).get('options',[])][:1]


def test_ten_thousand_cancels_only_first_melee_hit_and_expires(tmp_path):
    c,t,m=fight(tmp_path,[P+'TEN_THOUSAND_EDGES_FIND_NO_CENTER'],bundle_edit=hard_attack,cause=[{'type':'attack','attack_kind':'melee','no_damage':True}])
    settle(lambda a:act(t,m,'Dodge',a))
    e=reload(c,m);assert any(x.condition_id==TEN for x in e.state.actors[LEFT].conditions.values())
    turn(t,m,RIGHT)
    _,prompts=settle(lambda a:act(t,m,'Cause',a,target_id=LEFT),decline_steps)
    e=reload(c,m)
    assert any(x['context']['reaction_source_id']=='choice:needle.river_step' for x in prompts)
    assert any(x.event_type=='PASSIVE_TRIGGERED' and x.source_definition_id==P+'TEN_THOUSAND_EDGES_FIND_NO_CENTER' for x in e.events)
    count=len([x for x in e.events if x.event_type=='PASSIVE_TRIGGERED' and x.source_definition_id==P+'TEN_THOUSAND_EDGES_FIND_NO_CENTER'])
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT),decline_steps)
    e=reload(c,m)
    assert len([x for x in e.events if x.event_type=='PASSIVE_TRIGGERED' and x.source_definition_id==P+'TEN_THOUSAND_EDGES_FIND_NO_CENTER'])==count
    turn(t,m,LEFT)
    assert not any(x.condition_id==TEN for x in reload(c,m).state.actors[LEFT].conditions.values())

@pytest.mark.parametrize('case',['unowned','no_dodge','legacy','ranged'])
def test_ten_thousand_is_opt_in_and_melee_only(tmp_path,case):
    def legacy(b):
        hard_attack(b)
        if case=='legacy': b['typed_passives'][:]=[r for r in b['typed_passives'] if r.get('block')!='river_second_pass']
    c,t,m=fight(tmp_path,[] if case=='unowned' else [P+'TEN_THOUSAND_EDGES_FIND_NO_CENTER'],bundle_edit=legacy,
        cause=[{'type':'attack','attack_kind':'ranged' if case=='ranged' else 'melee','attack_bonus':100,'no_damage':True}])
    if case!='no_dodge': settle(lambda a:act(t,m,'Dodge',a))
    turn(t,m,RIGHT)
    _,prompts=settle(lambda a:act(t,m,'Cause',a,target_id=LEFT),decline_steps)
    e=reload(c,m)
    assert not any(p['context']['reaction_source_id']=='choice:needle.river_step' for p in prompts)
    assert not any(x.event_type=='PASSIVE_TRIGGERED' and x.source_definition_id==P+'TEN_THOUSAND_EDGES_FIND_NO_CENTER' for x in e.events)

@pytest.mark.parametrize('decline',[False,True])
def test_ten_thousand_optional_native_step(tmp_path,decline):
    c,t,m=fight(tmp_path,[P+'TEN_THOUSAND_EDGES_FIND_NO_CENTER'],bundle_edit=hard_attack,cause=[{'type':'attack','attack_kind':'melee','no_damage':True}])
    settle(lambda a:act(t,m,'Dodge',a));turn(t,m,RIGHT)
    before=reload(c,m).state.actors[LEFT].position
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT),decline_steps if decline else None)
    after=reload(c,m).state.actors[LEFT]
    assert (after.position==before)==decline
    assert after.reaction_available

@pytest.mark.parametrize('score,decline',[(50,False),(14,False),(50,True)])
def test_empty_bank_pays_once_and_moves_only_on_success(tmp_path,score,decline):
    c,t,m=fight(tmp_path,[P+'EMPTY_BANK_EVASION'],left_score=score,cause_save_dc=20,
        cause=[{'type':'save','ability':'dex','on_fail':[{'type':'damage','flat':20,'damage_types':['fire']}],
                'on_success':[{'type':'damage','flat':10,'damage_types':['fire']}]}])
    turn(t,m,RIGHT);before=reload(c,m).state.actors[LEFT]
    def choose(p):
        if decline and p['context']['reaction_source_id']=='choice:needle.river_bank': return []
        return [o['id'] for o in (p.get('choice') or {}).get('options',[])][:1]
    _,prompts=settle(lambda a:act(t,m,'Cause',a,target_id=LEFT),choose)
    e=reload(c,m);after=e.state.actors[LEFT]
    save=[x for x in e.events if x.event_type=='SAVE_ROLLED' and x.actor_id==LEFT][-1]
    success=save.payload['success']
    expected=(10 if success else 20) if decline else (0 if success else 10)
    assert after.current_hp==before.current_hp-expected
    assert after.resources[FOCUS]==before.resources[FOCUS]-(0 if decline else 1)
    assert (after.position!=before.position)==(success and not decline)
    prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.river_bank')
    assert 'Martial Focus' in str(prompt)

@pytest.mark.parametrize('decline',[False,True])
def test_draw_past_failed_save_chooses_legal_adjacent_space(tmp_path,decline):
    c,t,m=fight(tmp_path,[RESPONSE,P+'DRAW_PAST'],left_score=50)
    settle(lambda a:act(t,m,'Flowing Response: Draw Past',a));turn(t,m,RIGHT)
    before=reload(c,m).state.actors[RIGHT].position
    def choose(p):
        if p['context']['reaction_source_id']=='choice:needle.river_draw':
            ids=[o['id'] for o in p['choice']['options']]
            assert 'cell:3,6' not in ids
            return [] if decline else ids[:1]
        return decline_steps(p)
    _,prompts=settle(lambda a:act(t,m,'Unarmed Strike',a,target_id=LEFT),choose)
    e=reload(c,m)
    assert any(p['context']['reaction_source_id']=='choice:needle.river_draw' for p in prompts)
    assert (e.state.actors[RIGHT].position==before)==decline
    assert e._distance_actor_to_actor(e.state.actors[LEFT],e.state.actors[RIGHT])<=5


@pytest.mark.parametrize('native',[False,True])
def test_water_wears_stone_pb_damage_without_an_attack(tmp_path,native):
    def edit(b):
        for a in b['action_catalog']:
            if a['display_name']=='Cause' and native:
                a.update(resolution_kind='ATTACK',range_ft=None,reach_ft=5,attack_bonus=0,damage=None,damage_type='BLUDGEONING')
                a['parameters']={'attack_kind':'weapon'}
    c,t,m=fight(tmp_path,[RESPONSE,P+'WATER_WEARS_STONE'],left_score=50,bundle_edit=edit,
        cause=[{'type':'attack','attack_kind':'melee','no_damage':True}])
    settle(lambda a:act(t,m,'Flowing Response: Water Wears Stone',a));turn(t,m,RIGHT)
    before=reload(c,m).state.actors[RIGHT].current_hp
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT),decline_steps)
    e=reload(c,m)
    assert not any(v.source_definition_id.startswith('flowing_response:') for v in e.state.actors[LEFT].modifiers.values())
    assert e.state.actors[LEFT].reaction_available is False
    assert e.state.actors[RIGHT].current_hp==before-4
    assert len([x for x in e.events if x.event_type=='ATTACK_ROLLED'])==1


@pytest.mark.parametrize('native',[False,True])
def test_reed_in_storm_regains_only_absent_focus(tmp_path,native):
    def edit(b):
        for a in b['action_catalog']:
            if a['display_name']=='Cause' and native:
                a.update(resolution_kind='ATTACK',range_ft=None,reach_ft=5,attack_bonus=0,damage=None,damage_type='BLUDGEONING')
                a['parameters']={'attack_kind':'weapon'}
    c,t,m=fight(tmp_path,[P+'REED_IN_STORM'],left_score=50,
        bundle_edit=edit,cause=[{'type':'attack','attack_kind':'melee','no_damage':True}],
        prepare=[{'type':'spend_resource','resource_id':FOCUS,'flat':1}])
    settle(lambda a:act(t,m,'Dodge',a));settle(lambda a:act(t,m,'Prepare',a));turn(t,m,RIGHT)
    assert reload(c,m).state.actors[LEFT].resources[FOCUS]==0
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT),decline_steps)
    assert reload(c,m).state.actors[LEFT].resources[FOCUS]==1


def test_turning_guard_names_one_creature_and_optional_step(tmp_path):
    c,t,m=fight(tmp_path,[P+'TURNING_GUARD'],left_score=50)
    _,prompts=settle(lambda a:act(t,m,'Dodge',a))
    assert any(p['context']['reaction_source_id']=='choice:needle.river_guard' for p in prompts)
    e=reload(c,m);assert any(x.condition_id==GUARD and x.data['target']==RIGHT for x in e.state.actors[LEFT].conditions.values())
    turn(t,m,RIGHT);before=reload(c,m).state.actors[LEFT].position
    _,prompts=settle(lambda a:act(t,m,'Unarmed Strike',a,target_id=LEFT))
    assert any(p['context']['reaction_source_id']=='choice:needle.river_step' for p in prompts)
    assert reload(c,m).state.actors[LEFT].position!=before


def test_current_between_steps_marks_actual_reach_exit_and_expires(tmp_path):
    c,t,m=fight(tmp_path,[P+'CURRENT_BETWEEN_STEPS'])
    settle(lambda a:act(t,m,'Disengage',a))
    settle(cell_send(t,m,'Move',(2,6)))
    e=reload(c,m)
    assert any(x.condition_id==RETALIATE and x.data['target']==LEFT for x in e.state.actors[RIGHT].conditions.values())
    assert not any(x.condition_id==BETWEEN for x in e.state.actors[LEFT].conditions.values())
    turn(t,m,RIGHT);turn(t,m,LEFT)
    assert not any(x.condition_id==RETALIATE for x in reload(c,m).state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize('native',[False,True])
def test_current_retaliation_consumed_once_on_actual_melee_attack(tmp_path,native):
    def edit(b):
        for a in b['action_catalog']:
            if a['display_name']=='Cause':
                if native:
                    a.update(resolution_kind='ATTACK',range_ft=None,reach_ft=60,attack_bonus=0,damage=None,damage_type='BLUDGEONING')
                    a['parameters']={'attack_kind':'weapon'}
                else: a['parameters']['typed']['range_ft']=None
    c,t,m=fight(tmp_path,[P+'CURRENT_BETWEEN_STEPS'],left_score=50,bundle_edit=edit,
        cause=[{'type':'attack','attack_kind':'melee','no_damage':True}])
    settle(lambda a:act(t,m,'Disengage',a));settle(cell_send(t,m,'Move',(2,6)))
    turn(t,m,RIGHT)
    _,prompts=settle(lambda a:act(t,m,'Cause',a,target_id=LEFT),decline_steps)
    e=reload(c,m)
    assert [x for x in e.events if x.event_type=='ATTACK_ROLLED'][-1].payload['mode']=='DISADVANTAGE'
    assert any(p['context']['reaction_source_id']=='choice:needle.river_step' for p in prompts)
    assert not any(x.condition_id==RETALIATE for x in e.state.actors[RIGHT].conditions.values())
    _,prompts=settle(lambda a:act(t,m,'Cause',a,target_id=LEFT),decline_steps)
    e=reload(c,m)
    assert [x for x in e.events if x.event_type=='ATTACK_ROLLED'][-1].payload['mode']=='NORMAL'
    assert not any(p['context']['reaction_source_id']=='choice:needle.river_step' for p in prompts)


def test_ten_thousand_native_attack_and_optional_move(tmp_path):
    def native(b):
        for a in b['action_catalog']:
            if a['display_name']=='Cause':
                a.update(resolution_kind='ATTACK',range_ft=None,reach_ft=5,attack_bonus=100,damage=None,damage_type='BLUDGEONING')
                a['parameters']={'attack_kind':'weapon'}
    c,t,m=fight(tmp_path,[P+'TEN_THOUSAND_EDGES_FIND_NO_CENTER'],bundle_edit=native,
        cause=[{'type':'attack','attack_kind':'melee','no_damage':True}])
    settle(lambda a:act(t,m,'Dodge',a));turn(t,m,RIGHT)
    before=reload(c,m).state.actors[LEFT].position
    _,prompts=settle(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    e=reload(c,m)
    assert any(p['context']['reaction_source_id']=='choice:needle.river_step' for p in prompts)
    assert e.state.actors[LEFT].position!=before
    assert e.state.actors[LEFT].current_hp==1000



def test_response_step_precedes_draw_past_and_owner_chooses_both(tmp_path):
    c,t,m=fight(tmp_path,[RESPONSE,P+'DRAW_PAST'],left_score=50)
    settle(lambda a:act(t,m,'Flowing Response: Draw Past',a))
    settle(lambda a:act(t,m,'Flowing Response: step away',a))
    turn(t,m,RIGHT)
    before=reload(c,m).state.actors[LEFT].position
    _,prompts=settle(lambda a:act(t,m,'Unarmed Strike',a,target_id=LEFT))
    ids=[p['context']['reaction_source_id'] for p in prompts]
    assert ids.index('choice:needle.river_step')<ids.index('choice:needle.river_draw')
    e=reload(c,m)
    assert e.state.actors[LEFT].position!=before
    assert e._distance_actor_to_actor(e.state.actors[LEFT],e.state.actors[RIGHT])<=5
