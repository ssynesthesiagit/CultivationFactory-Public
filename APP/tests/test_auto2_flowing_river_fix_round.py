"""Fix-round interactions through committed table intents and cold mechanical replay."""
import pytest
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, fight, act, turn, cell_send
from tests.hunt15_support import action_sender
from tests.test_auto2_flowing_river import P, FOCUS, reload, settle, decline_steps
from combat.ext.flowing_second_pass import RETALIATE, GUARD


@pytest.mark.parametrize('native', [False, True])
def test_current_keeps_second_defenders_instance(tmp_path, native):
    def edit(b):
        aid = b['actor_template']['entity_id']
        b['actor_template']['initiative_bonus'] = {LEFT:100, ALLY:0, RIGHT:-100}[aid]
        if aid == ALLY:
            b['typed_passives'].append({'feature_id': P+'CURRENT_BETWEEN_STEPS', 'block': 'river_second_pass',
                                       'kind': 'between_steps', 'numbers': {'pb': 4}})
        for a in b['action_catalog']:
            if a['display_name'] == 'Cause':
                if native:
                    a.update(resolution_kind='ATTACK', range_ft=None, reach_ft=60, attack_bonus=-100, damage={'count':1,'sides':6,'modifier':0}, damage_type='BLUDGEONING')
                    a['parameters'] = {'attack_kind': 'weapon'}
                else:
                    a['parameters']['typed']['range_ft'] = None
                    a['parameters']['typed']['numbers']['attack_bonus'] = -100
    c,t,m = fight(tmp_path, [P+'CURRENT_BETWEEN_STEPS'], ally=(), bundle_edit=edit,
                  cause=[{'type':'attack','attack_kind':'melee','no_damage':True}])
    settle(lambda a: act(t,m,'Disengage',a)); settle(cell_send(t,m,'Move',(2,6)))
    turn(t,m,ALLY)
    settle(lambda a: act(t,m,'Disengage',a)); settle(cell_send(t,m,'Move',(2,5)))
    e=reload(c,m)
    marks=[x for x in e.state.actors[RIGHT].conditions.values() if x.condition_id==RETALIATE]
    assert {x.data['target'] for x in marks} == {LEFT,ALLY}
    surviving=next(x.instance_id for x in marks if x.data['target']==ALLY)
    consumed=next(x.instance_id for x in marks if x.data['target']==LEFT)
    turn(t,m,RIGHT)
    _,prompts=settle(lambda a: act(t,m,'Cause',a,target_id=LEFT),decline_steps)
    e=reload(c,m)
    assert surviving in e.state.actors[RIGHT].conditions
    removed=[x.payload['instance_id'] for x in e.events if x.event_type=='CONDITION_REMOVED' and x.payload.get('condition_id')==RETALIATE]
    assert removed==[consumed]
    assert any(p['context']['reaction_source_id']=='choice:needle.river_step' for p in prompts)
    _,prompts=settle(lambda a: act(t,m,'Cause',a,target_id=ALLY),decline_steps)
    e=reload(c,m)
    assert not any(x.condition_id==RETALIATE for x in e.state.actors[RIGHT].conditions.values())
    assert [x.payload['mode'] for x in e.events if x.event_type=='ATTACK_ROLLED'][-2:]==['DISADVANTAGE','DISADVANTAGE']
    assert any(p['context']['reaction_source_id']=='choice:needle.river_step' for p in prompts)


@pytest.mark.parametrize('ai_owner', [False, True])
def test_empty_bank_reaction_save_finishes_movement(tmp_path, ai_owner):
    def edit(b):
        if b['actor_template']['entity_id']==RIGHT:
            b['typed_reactions'].append({'feature_id':'reaction:test.visible_flame','name':'Visible Flame',
                'block':'generic','kind':'missed','range_ft':60,'numbers':{'save_dc':1,'pb':4},
                'effects':[{'type':'save','ability':'dex',
                    'on_fail':[{'type':'damage','flat':20,'damage_types':['fire']}],
                    'on_success':[{'type':'damage','flat':10,'damage_types':['fire']},
                                  {'type':'condition','condition':'prone','applies_to':'target'}]}]})
        for a in b['action_catalog']:
            if a['display_name']=='Prepare':
                a['parameters']['typed']['range_ft']=None
    c,t,m=fight(tmp_path,[P+'EMPTY_BANK_EVASION'],left_score=50,bundle_edit=edit,
                prepare=[{'type':'attack','attack_kind':'melee','no_damage':True}],prepare_attack_bonus=-100)
    before=reload(c,m).state.actors[LEFT]
    send=action_sender(c,t,m,'Prepare',ai=True) if ai_owner else lambda a: act(t,m,'Prepare',a)
    _,prompts=settle(send)
    e=reload(c,m);after=e.state.actors[LEFT]
    assert after.current_hp==before.current_hp
    assert after.resources[FOCUS]==before.resources[FOCUS]-1
    assert after.position!=before.position
    assert any(x.condition_id.endswith('.prone') for x in after.conditions.values())
    assert any(x.event_type=='REACTION_RESOLVED' and x.source_definition_id=='reaction:test.visible_flame' for x in e.events)
    steps=[p for p in prompts if p['context']['reaction_source_id']=='choice:needle.river_step']
    if ai_owner:
        assert not steps
    else:
        assert steps
        assert 'successful Dexterity save' in str(steps[0]) and 'Visible Flame' in str(steps[0])
        assert 'missed or failed' not in str(steps[0])


def test_turning_guard_pill_explains_selected_creature_and_step(tmp_path):
    c,t,m=fight(tmp_path,[P+'TURNING_GUARD'])
    settle(lambda a: act(t,m,'Dodge',a))
    guard=next(x for x in reload(c,m).state.actors[LEFT].conditions.values() if x.condition_id==GUARD)
    assert 'Visitor' in guard.data['label'] and '5 feet' in guard.data['label']


@pytest.mark.parametrize('ai_owner', [False,True])
def test_ai_attacker_respects_manual_or_automatic_step_owner(tmp_path, ai_owner):
    def edit(b):
        for a in b['action_catalog']:
            if a['display_name']=='Cause':
                a['parameters']['typed']['range_ft']=None
                a['parameters']['typed']['numbers']['attack_bonus']=100
    c,t,m=fight(tmp_path,[P+'TEN_THOUSAND_EDGES_FIND_NO_CENTER'],bundle_edit=edit,
                cause=[{'type':'attack','attack_kind':'melee','on_hit':[{'type':'damage','flat':20,'damage_types':['bludgeoning']}]}])
    settle(lambda a: act(t,m,'Dodge',a));turn(t,m,RIGHT)
    if ai_owner: c.set_controller_mode(m,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    before=reload(c,m).state.actors[LEFT]
    send=action_sender(c,t,m,'Cause',ai=True,target_id=LEFT)
    _,prompts=settle(send)
    after=reload(c,m).state.actors[LEFT]
    assert after.current_hp==before.current_hp
    assert after.position!=before.position
    assert bool([p for p in prompts if p['context']['reaction_source_id']=='choice:needle.river_step']) == (not ai_owner)


@pytest.mark.parametrize('native', [False,True])
def test_ten_thousand_prevents_real_damage_only_once(tmp_path,native):
    def edit(b):
        for a in b['action_catalog']:
            if a['display_name']=='Cause':
                if native:
                    a.update(resolution_kind='ATTACK',range_ft=None,reach_ft=60,attack_bonus=100,
                             damage={'count':1,'sides':6,'modifier':20},damage_type='BLUDGEONING')
                    a['parameters']={'attack_kind':'weapon'}
                else:
                    a['parameters']['typed']['range_ft']=None
                    a['parameters']['typed']['numbers']['attack_bonus']=100
    c,t,m=fight(tmp_path,[P+'TEN_THOUSAND_EDGES_FIND_NO_CENTER'],bundle_edit=edit,
                cause=[{'type':'attack','attack_kind':'melee',
                        'on_hit':[{'type':'damage','flat':20,'damage_types':['bludgeoning']}]}])
    settle(lambda a:act(t,m,'Dodge',a));turn(t,m,RIGHT)
    before=reload(c,m).state.actors[LEFT].current_hp
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT),decline_steps)
    assert reload(c,m).state.actors[LEFT].current_hp==before
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT),decline_steps)
    assert reload(c,m).state.actors[LEFT].current_hp<=before-20


@pytest.mark.parametrize('native',[False,True])
def test_reed_in_storm_does_not_regain_full_focus(tmp_path,native):
    def edit(b):
        for a in b['action_catalog']:
            if a['display_name']=='Cause':
                if native:
                    a.update(resolution_kind='ATTACK',range_ft=None,reach_ft=60,attack_bonus=-100,
                             damage={'count':1,'sides':6,'modifier':0},damage_type='BLUDGEONING')
                    a['parameters']={'attack_kind':'weapon'}
                else:
                    a['parameters']['typed']['range_ft']=None
                    a['parameters']['typed']['numbers']['attack_bonus']=-100
    c,t,m=fight(tmp_path,[P+'REED_IN_STORM'],bundle_edit=edit,
                cause=[{'type':'attack','attack_kind':'melee','no_damage':True}])
    settle(lambda a:act(t,m,'Dodge',a));turn(t,m,RIGHT)
    before=reload(c,m);assert before.state.actors[LEFT].resources[FOCUS]==1
    sequence=before.state.event_sequence
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT),decline_steps)
    e=reload(c,m)
    assert e.state.actors[LEFT].resources[FOCUS]==1
    assert not any(x.event_type=='RESOURCE_GAINED' and x.source_definition_id==P+'REED_IN_STORM'
                   for x in e.events if x.sequence>sequence)


def test_response_successful_control_save_prompt_names_trigger(tmp_path):
    c,t,m=fight(tmp_path,[P+'FLOWING_RESPONSE'],left_score=50,cause_save_dc=1,
                cause=[{'type':'save','ability':'str',
                        'on_fail':[{'type':'condition','condition':'prone','applies_to':'target'}],
                        'on_success':[]}])
    settle(lambda a:act(t,m,'Flowing Response: step away',a));turn(t,m,RIGHT)
    _,prompts=settle(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    reload(c,m)
    step=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.river_step')
    assert 'successful saving throw' in str(step) and 'Cause' in str(step)
    assert 'missed or failed' not in str(step)


def test_consolidated_reviews_have_one_authority_and_execute(tmp_path):
    import json
    from pathlib import Path
    c,t,m=fight(tmp_path,[P+'TURNING_GUARD'])
    settle(lambda a:act(t,m,'Dodge',a));reload(c,m)
    folder=Path(__file__).resolve().parents[1]/'authority/typed_mechanics/reviewed_final.d'
    rows=[json.loads(p.read_text()) for p in folder.glob('*.json')]
    for name in ('TURNING_GUARD','EMPTY_BANK_EVASION','REED_IN_STORM','WATER_WEARS_STONE','DRAW_PAST','FLOWING_RESPONSE'):
        assert sum(P+name in row.get('mechanics',row) for row in rows)==1, name
