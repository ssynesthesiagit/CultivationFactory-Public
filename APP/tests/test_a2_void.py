"""Printed Void riders through CombatService, session intents and cold reload."""
import pytest
from tests.auto_worker1_support import LEFT, RIGHT, fight, reload, action_sender, act
from tests.void_support import settle, turn, cell_send

SHELL='TAL_VOID_VOID_SHELL'
PURCHASE='TAL_VOID_NO_PURCHASE_BODY'
SOVEREIGN='TAL_VOID_VOID_SOVEREIGN_INCARNATION'
NEEDLE='TAL_VOID_VOID_NEEDLE'
STEP='TAL_VOID_EMPTY_STEP'


def attack(kind='cultivation_melee', damage=False):
    return [{'type':'attack','attack_kind':kind,'count':1,
             'on_hit':([{'type':'damage','flat':1,'damage_types':['force']}] if damage else [])}]


def accurate(bundle):
    for action in bundle['action_catalog']:
        if action['display_name']=='Cause':
            action['parameters']['typed']['numbers']['attack_bonus']=100
            action['parameters']['typed']['range_ft']=None


def rolls(e):
    return [v for v in e.events if v.event_type=='ATTACK_ROLLED']


def landing(p,x,y):
    options=(p.get('choice') or {}).get('options') or []
    ids=[o['id'] for o in options]
    wanted=f'{x},{y}'
    return [next(i for i in ids if i.endswith(wanted))] if any(i.endswith(wanted) for i in ids) else pressure(p)


def pressure(p, choice='cost_lock'):
    options=(p.get('choice') or {}).get('options') or []
    ids=[o['id'] for o in options]
    return [choice] if choice in ids else ids[:max(1,(p.get('choice') or {}).get('minimum',1))]


@pytest.mark.parametrize('damage',[False,True])
def test_shell_confirmed_hit_once_per_actual_turn(tmp_path,damage):
    c,t,m=fight(tmp_path,[SHELL],cause=attack(damage=damage),right_score=214,bundle_edit=accurate)
    settle(action_sender(c,t,m,'Void Shell'))
    turn(t,m,RIGHT)
    for _ in range(2):settle(action_sender(c,t,m,'Cause',target_id=LEFT))
    e=reload(c,m)
    assert all(v.payload['provisional_hit'] for v in rolls(e))
    retaliations=[v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and RIGHT in v.target_ids]
    assert len(retaliations)==1 and retaliations[0].payload['hp_damage']==4
    assert e.state.actors[RIGHT].current_hp==996
    turn(t,m,LEFT);turn(t,m,RIGHT)
    settle(action_sender(c,t,m,'Cause',target_id=LEFT))
    assert reload(c,m).state.actors[RIGHT].current_hp==992


@pytest.mark.parametrize('kind',['cultivation_ranged','weapon'])
def test_shell_does_not_retaliate_for_other_attack_deliveries(tmp_path,kind):
    c,t,m=fight(tmp_path,[SHELL],cause=attack(kind),right_score=214,bundle_edit=accurate)
    settle(action_sender(c,t,m,'Void Shell'))
    turn(t,m,RIGHT)
    settle(action_sender(c,t,m,'Cause',target_id=LEFT))
    assert reload(c,m).state.actors[RIGHT].current_hp==1000


def test_shell_legacy_saved_packet_keeps_damage_timing(tmp_path):
    def legacy(bundle):
        for a in bundle['action_catalog']:
            typed=a.get('parameters',{}).get('typed',{})
            typed['effects']=[r for r in typed.get('effects',[]) if r.get('condition')!='void_shell_hits']
    c,t,m=fight(tmp_path,[SHELL],cause=attack(),right_score=214,bundle_edit=lambda b:(legacy(b),accurate(b)))
    settle(action_sender(c,t,m,'Void Shell'))
    turn(t,m,RIGHT);settle(action_sender(c,t,m,'Cause',target_id=LEFT))
    assert reload(c,m).state.actors[RIGHT].current_hp==1000


@pytest.mark.parametrize('choice,condition',[('cost_lock','void_cost_lock'),('vitality','no_temp_hp'),('invisibility','no_invisible')])
def test_no_purchase_optional_zero_damage_melee_hit(tmp_path,choice,condition):
    c,t,m=fight(tmp_path,[SHELL,PURCHASE],cause=attack('weapon'),right_score=214,bundle_edit=accurate)
    settle(action_sender(c,t,m,'Void Shell'))
    turn(t,m,RIGHT)
    _,prompts=settle(action_sender(c,t,m,'Cause',target_id=LEFT),lambda p:pressure(p,choice))
    assert any(p['context']['reaction_source_id'].endswith('void_no_purchase') for p in prompts)
    e=reload(c,m)
    assert any(x.condition_id.endswith('.'+condition) for x in e.state.actors[RIGHT].conditions.values())
    assert e.state.actors[RIGHT].current_hp==1000
    _,prompts=settle(action_sender(c,t,m,'Cause',target_id=LEFT))
    assert not any(p['context']['reaction_source_id'].endswith('void_no_purchase') for p in prompts)
    turn(t,m,LEFT)
    assert not any(x.condition_id.endswith('.'+condition) for x in reload(c,m).state.actors[RIGHT].conditions.values())


def test_no_purchase_decline_keeps_allowance(tmp_path):
    c,t,m=fight(tmp_path,[SHELL,PURCHASE],cause=attack('weapon'),right_score=214,bundle_edit=accurate)
    settle(action_sender(c,t,m,'Void Shell'));turn(t,m,RIGHT)
    settle(action_sender(c,t,m,'Cause',target_id=LEFT),lambda p:[])
    assert not any(x.condition_id.endswith('.void_cost_lock') for x in reload(c,m).state.actors[RIGHT].conditions.values())
    settle(action_sender(c,t,m,'Cause',target_id=LEFT),lambda p:pressure(p))
    assert any(x.condition_id.endswith('.void_cost_lock') for x in reload(c,m).state.actors[RIGHT].conditions.values())


def test_no_purchase_without_shell_has_no_prompt(tmp_path):
    c,t,m=fight(tmp_path,[PURCHASE],cause=attack('weapon'),right_score=214,bundle_edit=accurate)
    turn(t,m,RIGHT)
    _,prompts=settle(action_sender(c,t,m,'Cause',target_id=LEFT))
    assert not prompts
    assert not reload(c,m).state.actors[RIGHT].conditions


def test_no_purchase_has_its_own_pressure_allowance_and_is_not_a_needle_hit(tmp_path):
    c,t,m=fight(tmp_path,[SHELL,PURCHASE,NEEDLE,'TAL_VOID_COST_DENYING_NEEDLE'],
        cause=attack('weapon'),right_score=214,left_attack_bonus=100,bundle_edit=accurate)
    settle(action_sender(c,t,m,'Void Shell'))
    settle(action_sender(c,t,m,'Void Needle: Cost Lock',target_id=RIGHT),lambda p:pressure(p))
    def deny_reminders(e):
        return sum(v.event_type=='GM_RIDER' and 'Cost-Denying Needle on' in str(v.payload) for v in e.events)
    before=deny_reminders(reload(c,m))
    assert before==1
    turn(t,m,RIGHT)
    _,prompts=settle(action_sender(c,t,m,'Cause',target_id=LEFT),lambda p:pressure(p))
    assert any(p['context']['reaction_source_id'].endswith('void_no_purchase') for p in prompts)
    assert deny_reminders(reload(c,m))==before


def test_sovereign_needle_two_chosen_creatures_and_single_pressure(tmp_path):
    c,t,m=fight(tmp_path,[SOVEREIGN,NEEDLE],extra_witness=True,left_attack_bonus=100)
    assert not any(g['label'].endswith('(up to two creatures)') for g in t.state(m)['menu']['actions'])
    settle(action_sender(c,t,m,'Void-Sovereign Incarnation'))
    witness='actor:factory.auto111-witness'
    def pick(p):
        if p['context']['reaction_source_id'].endswith('rider_targets'):return [RIGHT,witness]
        return pressure(p)
    settle(action_sender(c,t,m,'Void Needle: Cost Lock (up to two creatures)'),pick)
    e=reload(c,m)
    for who in (RIGHT,witness):
        assert e.state.actors[who].current_hp<1000
        assert any(x.condition_id.endswith('.hollowed') for x in e.state.actors[who].conditions.values())
    assert not any(v.event_type=='GM_RIDER' for v in e.events)
    assert len(rolls(e))==2
    assert sum(any(x.condition_id.endswith('.void_cost_lock') for x in e.state.actors[who].conditions.values()) for who in (RIGHT,witness))==1
    assert not any(g['label'].startswith('Void-Sovereign Incarnation') for g in t.state(m)['menu']['actions'])


def test_sovereign_costless_step_at_zero_cp_is_once_per_turn(tmp_path):
    c,t,m=fight(tmp_path,[SOVEREIGN,STEP],prepare_target='SELF',prepare=[{'type':'spend_resource','resource_id':'resource:core.qi','flat':100}])
    settle(action_sender(c,t,m,'Void-Sovereign Incarnation'))
    turn(t,m,RIGHT);turn(t,m,LEFT)
    settle(action_sender(c,t,m,'Prepare'))
    assert reload(c,m).state.actors[LEFT].resources['resource:core.qi']==0
    settle(cell_send(t,m,'Empty Step (no cost)',(2,6)),lambda p: landing(p,2,6))
    assert reload(c,m).state.actors[LEFT].position.x==2
    assert not any(g['label']=='Empty Step (no cost)' for g in t.state(m)['menu']['actions'])
    turn(t,m,RIGHT);turn(t,m,LEFT)
    assert any(g['label']=='Empty Step (no cost)' for g in t.state(m)['menu']['actions'])


def test_sovereign_grants_step_and_flight_suppression_keeps_other_benefits(tmp_path):
    c,t,m=fight(tmp_path,[SOVEREIGN,NEEDLE],prepare_target='SELF',
        prepare=[{'type':'remove_condition','condition':'void_sovereign_flight','applies_to':'self'}])
    assert not any(g['label']=='Empty Step (no cost)' for g in t.state(m)['menu']['actions'])
    settle(action_sender(c,t,m,'Void-Sovereign Incarnation'))
    turn(t,m,RIGHT);turn(t,m,LEFT)
    settle(action_sender(c,t,m,'Prepare'))
    e=reload(c,m)
    assert not any(x.condition_id.endswith('.void_sovereign_flight') for x in e.state.actors[LEFT].conditions.values())
    assert any(g['label'].endswith('(up to two creatures)') for g in t.state(m)['menu']['actions'])
    before=e.state.actors[LEFT].resources['resource:core.qi']
    settle(cell_send(t,m,'Empty Step (no cost)',(2,6)),lambda p:landing(p,2,6))
    e=reload(c,m)
    assert e.state.actors[LEFT].position.x==2
    assert e.state.actors[LEFT].resources['resource:core.qi']==before
    assert not any(g['label']=='Empty Step (no cost)' for g in t.state(m)['menu']['actions'])


def test_sovereign_confirmed_hollowed_miss_chooses_landing_without_reaction(tmp_path):
    c,t,m=fight(tmp_path,[SOVEREIGN],prepare=[{'type':'condition','condition':'hollowed','applies_to':'target','duration':'one_minute'}],cause=attack('weapon'),right_score=1)
    settle(action_sender(c,t,m,'Prepare',target_id=RIGHT))
    settle(action_sender(c,t,m,'Void-Sovereign Incarnation'))
    turn(t,m,RIGHT)
    _,prompts=settle(action_sender(c,t,m,'Cause',target_id=LEFT))
    e=reload(c,m)
    assert rolls(e) and not rolls(e)[-1].payload['provisional_hit']
    assert any(p['context']['reaction_source_id'].endswith('void_sovereign_step') for p in prompts)
    assert any(v.event_type=='MOVEMENT_COMMITTED' and v.actor_id==LEFT for v in e.events)
    assert e.state.actors[LEFT].reaction_available
    assert e.state.actors[LEFT].resources['resource:core.qi']==90


def test_sovereign_second_missed_attack_step_pays_normal_cost(tmp_path):
    c,t,m=fight(tmp_path,[SOVEREIGN],prepare=[{'type':'condition','condition':'hollowed','applies_to':'target','duration':'one_minute'}],cause=attack('weapon'),right_score=1)
    settle(action_sender(c,t,m,'Prepare',target_id=RIGHT))
    settle(action_sender(c,t,m,'Void-Sovereign Incarnation'));turn(t,m,RIGHT)
    # Each accepted step gets a player-selected landing; the second pays.
    for index in range(2):
        _,prompts=settle(action_sender(c,t,m,'Cause',target_id=LEFT),lambda p:landing(p,2 if index==0 else 3,6))
        assert any(p['context']['reaction_source_id'].endswith('void_sovereign_step') for p in prompts)
        e=reload(c,m)
        assert e.state.actors[LEFT].resources['resource:core.qi']==90-index
        assert e.state.actors[LEFT].reaction_available


def test_no_purchase_native_opportunity_hit_uses_settled_melee_notice(tmp_path):
    from tests.hunt12_support import send
    c,t,m=fight(tmp_path,[SHELL,PURCHASE],right_score=214,
        positions={LEFT:{'x':6,'y':6},RIGHT:{'x':7,'y':6}})
    settle(action_sender(c,t,m,'Void Shell'));turn(t,m,RIGHT);turn(t,m,LEFT)
    e=c._load_session(m).engine
    move=next(v for v in e.legal_candidates() if v.destination is not None
              and v.display_name.startswith('Move to ') and (v.destination.x,v.destination.y)==(5,6))
    _,prompts=settle(lambda answers:send(c,t,m,move,
        [{**a,'selection':'USE'} if not a.get('option_ids') else a for a in answers]),lambda p:pressure(p))
    e=reload(c,m)
    assert any(p['context']['reaction_source_id'].endswith('void_no_purchase') for p in prompts)
    assert any(x.condition_id.endswith('.void_cost_lock') for x in e.state.actors[RIGHT].conditions.values())
