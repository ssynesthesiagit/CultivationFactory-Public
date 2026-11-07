"""Second-pass rules through committed session intents, cold reload and replay."""
import pytest
OPENING = 'condition:typed.pp_heartbeat_opening'
USED = 'condition:typed.pp_recovery_used.'
PATIENT = 'condition:typed.pp_patient_subject'
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, fight, act, turn, reload, settle, action_sender
P = 'tianxia.talent.pressure_points.'
FOCUS = 'resource:core.martial_focus'


def send_prefix(c, t, m, prefix, *, target=None, ai=False):
    name = next(g['label'] for g in t.state(m)['menu']['actions'] if g['label'].startswith(prefix) and any(target is None or target in o.get('target_ids',[]) for o in g['options']))
    return action_sender(c, t, m, name, ai=ai, target_id=target)


def option(prefix):
    def choose(prompt):
        ids = [o['id'] for o in (prompt.get('choice') or {}).get('options', [])]
        return [next(o for o in ids if o.startswith(prefix))] if any(o.startswith(prefix) for o in ids) else ids[:max(1, (prompt.get('choice') or {}).get('minimum', 1))]
    return choose


def conditions(e, aid, name):
    return [c for c in e.state.actors[aid].conditions.values() if c.condition_id == name]


@pytest.mark.parametrize('name', ['poisoned', 'frightened'])
def test_gentle_release_repeats_exactly_one_original_save_without_temp_hp(tmp_path, name):
    prep = [{'type': 'save', 'ability': 'con', 'on_fail': [{'type': 'condition', 'condition': name, 'applies_to': 'target', 'duration': 'until_removed'}], 'on_success': []}]
    c, t, m = fight(tmp_path, [P+'gentle_release'], prepare=prep, prepare_target='ANY_CREATURE', left_save_dc=100, right_team='team:factory')
    settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    assert conditions(reload(c, m), RIGHT, 'condition:typed.'+name)
    before = len(reload(c, m).events)
    settle(send_prefix(c, t, m, 'Gentle Release', target=RIGHT), choose=option('repeat:'))
    e = reload(c, m)
    saves = [v for v in e.events[before:] if v.event_type == 'SAVE_ROLLED']
    assert len(saves) == 1 and saves[0].payload['dc'] == 100
    assert e.state.actors[RIGHT].temporary_hp == 0
    assert conditions(e, RIGHT, USED+'gentle')
    # Limit is on the recipient, not a healer's action counter.
    turn(t, m, RIGHT); turn(t, m, LEFT)
    assert not any(RIGHT in o.get('target_ids', []) for g in t.state(m)['menu']['actions']
                   if g['label'].startswith('Gentle Release') for o in g['options'])


@pytest.mark.parametrize('ai', [False, True])
def test_gentle_release_temp_hp_is_one_benefit_and_does_not_help_enemies(tmp_path, ai):
    c, t, m = fight(tmp_path, [P+'gentle_release'], ally=[])
    settle(send_prefix(c, t, m, 'Gentle Release', target=ALLY, ai=ai), choose=option('temp_hp'))
    e = reload(c, m)
    assert e.state.actors[ALLY].temporary_hp == 4
    assert e.state.actors[RIGHT].temporary_hp == 0
    assert conditions(e, ALLY, USED+'gentle')
    # AI candidates obey side as an admission rule, including the willing-enemy variant.
    from combat.ext.pressure_points_second_pass import recovery_ai_side
    owner = e.state.actors[LEFT]
    from types import SimpleNamespace
    action = next(a for a in e.action_catalog.values() if a.owner_id == LEFT and a.display_name.startswith('Gentle Release'))
    assert recovery_ai_side(e, owner, SimpleNamespace(target_ids=[RIGHT]), action) is False


@pytest.mark.parametrize('pay', ['2 CP', 'Martial Focus'])
def test_life_gate_ends_one_condition_and_pays_the_selected_cost(tmp_path, pay):
    c, t, m = fight(tmp_path, [P+'life_gate_touch'], right_team='team:factory', prepare_target='ANY_CREATURE',
        prepare=[{'type':'condition','condition':n,'applies_to':'target','duration':{'kind':'until_removed'}} for n in ('poisoned','frightened')])
    settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    e = reload(c, m); qi=e.state.actors[LEFT].resources['resource:core.qi']; focus=e.state.actors[LEFT].resources[FOCUS]
    labels = [g['label'] for g in t.state(m)['menu']['actions'] if g['label'].startswith('Life Gate Touch')]
    label=next(n for n in labels if ('Martial Focus' in n) == (pay == 'Martial Focus'))
    settle(lambda a: act(t, m, label, a, target_id=RIGHT), choose=option('end:'))
    e=reload(c,m)
    assert sum(bool(conditions(e,RIGHT,'condition:typed.'+n)) for n in ('poisoned','frightened')) == 1
    assert conditions(e, RIGHT, USED+'life')
    assert e.state.actors[LEFT].resources['resource:core.qi'] == qi - (2 if pay=='2 CP' else 0)
    assert e.state.actors[LEFT].resources[FOCUS] == focus - (pay=='Martial Focus')
    assert not [v for v in e.events if v.event_type=='HEALING_APPLIED']


@pytest.mark.parametrize('success', [False, True])
def test_pulse_diagnosis_rolls_medicine_and_reveals_only_the_selected_facts(tmp_path, success):
    c,t,m=fight(tmp_path,[P+'pulse_diagnosis'], right_team='team:factory',left_score=50 if success else 1)
    def choose(p):
        ids=[o['id'] for o in p.get('choice',{}).get('options',[])]
        if '20' in ids:return ['20']
        if 'weakest' in ids:return ['weakest','illness'] if success else ['weakest']
        return ids[:1]
    settle(send_prefix(c,t,m,'Pulse Diagnosis',target=RIGHT),choose=choose)
    e=reload(c,m)
    checks=[v for v in e.events if v.event_type=='CHECK_ROLLED']
    assert len(checks)==1 and checks[0].payload['skill']=='Medicine' and checks[0].payload['dc']==20
    assert checks[0].payload['success']==success
    facts=[v for v in e.events if v.payload.get('diagnosis')]
    assert len(facts)==(2 if success else 1)
    assert {v.payload['diagnosis'] for v in facts}==({'weakest','illness'} if success else {'weakest'})


def test_patient_hand_ai_picks_perceived_enemy_with_ally_in_range(tmp_path):
    c,t,m=fight(tmp_path,[P+'patient_hand'],ally=[],prepare_target='SELF',
        prepare=[{'type':'temp_hp','applies_to':'self','flat':1}],prepare_costs=[(FOCUS,1)])
    settle(lambda a: act(t,m,'Prepare',a))
    settle(action_sender(c,t,m,'Dodge',ai=True))
    e=reload(c,m)
    grants=conditions(e,LEFT,PATIENT)
    assert len(grants)==1 and grants[0].data['subject']==RIGHT
    assert e.state.actors[LEFT].resources[FOCUS]==1


def test_patient_hand_advantage_on_actual_diagnosis_is_consumed_then_expires(tmp_path):
    c,t,m=fight(tmp_path,[P+'patient_hand',P+'pulse_diagnosis'],right_team='team:factory',extra_witness=True,
        prepare_target='SELF',prepare=[{'type':'temp_hp','applies_to':'self','flat':1}],prepare_costs=[(FOCUS,1)])
    settle(lambda a:act(t,m,'Prepare',a))
    settle(lambda a:act(t,m,'Dodge',a),choose=option(RIGHT))
    assert conditions(reload(c,m),LEFT,PATIENT)[0].data['subject']==RIGHT
    turn(t,m,RIGHT);turn(t,m,LEFT)
    settle(send_prefix(c,t,m,'Pulse Diagnosis',target=RIGHT))
    e=reload(c,m)
    checks=[v for v in e.events if v.event_type=='CHECK_ROLLED' and v.payload.get('skill')=='Medicine']
    assert checks[-1].payload['actor']['mode']=='ADVANTAGE'
    assert not conditions(e,LEFT,PATIENT)


@pytest.mark.parametrize('failed', [False,True])
def test_heartbeats_delivers_bonus_only_on_first_later_attack_and_correct_branch(tmp_path,failed):
    strike={'type':'attack','attack_kind':'unarmed','range_ft':5,'on_hit':[{'type':'damage','dice':{'count':1,'sides':6},'damage_types':['bludgeoning'],'applies_to':'target'}]}
    c,t,m=fight(tmp_path,[P+'the_point_between_heartbeats'],right_score=14 if failed else 214,
        left_attack_bonus=100,extra_actions=(('Follow-up strike',{'target_kind':'HOSTILE_ENTITY','effects':[strike]}),))
    settle(send_prefix(c,t,m,'The Point Between Heartbeats',target=RIGHT))
    e=reload(c,m)
    assert e.state.actors[RIGHT].current_hp==1000 and conditions(e,RIGHT,OPENING)
    assert e._effective_speed(e.state.actors[RIGHT])==(0 if failed else 15)
    for _ in range(2):settle(lambda a:act(t,m,'Follow-up strike',a,target_id=RIGHT))
    e=reload(c,m)
    attacks=[v for v in e.events if v.event_type=='ATTACK_ROLLED']
    assert [v.payload['mode'] for v in attacks]==['ADVANTAGE','NORMAL']
    assert not conditions(e,RIGHT,OPENING)
    bonus=[r for r in e.rolls if r.expression in {'6d10','6d10+0','12d10','12d10+0'}]
    assert len(bonus)==int(failed)
    if failed:
        assert [v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and v.payload.get('damage_type')=='FORCE']


def test_heartbeats_miss_consumes_damage_opening_without_a_bonus_roll(tmp_path):
    strike={'type':'attack','attack_kind':'unarmed','range_ft':5,'on_hit':[{'type':'damage','flat':1,'damage_types':['bludgeoning'],'applies_to':'target'}]}
    def miss_bonus(b):
        for a in b['action_catalog']:
            if a['display_name'] == 'Miss': a['parameters']['typed']['numbers']['attack_bonus']=-100
    c,t,m=fight(tmp_path,[P+'the_point_between_heartbeats'],left_attack_bonus=-100,bundle_edit=miss_bonus,
        extra_actions=(('Miss',{'target_kind':'HOSTILE_ENTITY','effects':[strike]}),))
    settle(send_prefix(c,t,m,'The Point Between Heartbeats',target=RIGHT))
    settle(lambda a:act(t,m,'Miss',a,target_id=RIGHT))
    e=reload(c,m)
    assert not conditions(e,RIGHT,OPENING)
    assert not [r for r in e.rolls if 'd10' in r.expression]


def test_shut_heaven_gate_stunned_immunity_delivers_dazed_on_failed_save(tmp_path):
    c,t,m=fight(tmp_path,[P+'shut_the_heaven_gate'],left_score=50,prepare=[
        {'type':'mark','mark':'Pressure Point','applies_to':'target','duration':{'kind':'until_removed'}},
        {'type':'condition','condition':'immunity_test','applies_to':'target','duration':{'kind':'until_removed'},
         'condition_data':{'rule':{'condition_immunities':['stunned']}}}])
    settle(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    settle(lambda a:act(t,m,'Unarmed Strike',a,target_id=RIGHT))
    e=reload(c,m)
    assert not conditions(e,RIGHT,'condition:typed.stunned')
    assert conditions(e,RIGHT,'condition:typed.pp_dazed')
    assert [v for v in e.events if v.event_type=='SAVE_ROLLED'][-1].payload['success'] is False
    turn(t,m,RIGHT);turn(t,m,LEFT)
    assert not conditions(reload(c,m),RIGHT,'condition:typed.pp_dazed')


def test_stolen_step_preexisting_point_offers_half_speed_even_with_known_seal(tmp_path):
    c,t,m=fight(tmp_path,[P+'stolen_pulse_step',P+'breath_seal'],left_score=50,
        prepare=[{'type':'mark','mark':'Pressure Point','applies_to':'target','duration':{'kind':'until_removed'}}])
    settle(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    settle(lambda a:act(t,m,'Touch the Point: Stolen Pulse Step',a))
    settle(lambda a:act(t,m,'Touch the Point: Apply a Point even to a marked creature',a))
    def choose(p):
        ids=[o['id'] for o in p.get('choice',{}).get('options',[])]
        if 'half_speed' in ids:return ['half_speed']
        if 'cell:3,3' in ids:return ['cell:3,3']
        # Cell encoding uses a different separator in older schemas; choose by readable coordinates.
        dest=next((o['id'] for o in p.get('choice',{}).get('options',[]) if '3,3 ' in o.get('label','')),None)
        return [dest] if dest else ids[:1]
    _,prompts=settle(lambda a:act(t,m,'Unarmed Strike',a,target_id=RIGHT),choose=choose)
    e=reload(c,m)
    assert any('half_speed' in [o['id'] for o in p.get('choice',{}).get('options',[])] for p in prompts)
    assert any('15 feet' in str(p.get('trigger_context') or p) for p in prompts)
    assert e.state.actors[LEFT].position.y==3
    assert not [v for v in e.events if v.event_type=='SAVE_ROLLED']


@pytest.mark.parametrize('secret', [False, True])
def test_meridian_field_triggers_for_ordinary_technique_but_exempts_secrets(tmp_path, secret):
    from tests.auto_worker1_support import cell_send
    # Explicit classified source metadata belongs to the sealed synthetic trigger.
    # The field still runs through its real compiled action and native zone trigger.
    def classify(b):
        for a in b['action_catalog']:
            if a['display_name']=='Cause':
                typed=a['parameters']['typed']
                typed['source']='test:field.technique'
                if secret:typed['source_category']='Secret Inheritance'
    c,t,m=fight(tmp_path,[P+'meridian_stillness_field'],bundle_edit=classify,
        prepare=[{'type':'mark','mark':'Pressure Point','applies_to':'target','duration':{'kind':'until_removed'}}],
        cause_target='SELF',cause=[{'type':'temp_hp','applies_to':'self','flat':1}],ally=[])
    settle(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    settle(cell_send(t,m,'Meridian Stillness Field',(4,6)))
    e=reload(c,m); assert e._effective_speed(e.state.actors[RIGHT])==20
    assert e._effective_speed(e.state.actors[ALLY])==30
    before=len(e.events)
    turn(t,m,RIGHT)
    settle(lambda a:act(t,m,'Cause',a))
    settle(lambda a:act(t,m,'Cause',a))
    e=reload(c,m)
    saves=[v for v in e.events[before:] if v.event_type=='SAVE_ROLLED' and v.actor_id==RIGHT]
    assert len(saves)==int(not secret)
    assert not [v for v in e.events[before:] if v.event_type=='DAMAGE_COMMITTED' and ALLY in v.target_ids]


@pytest.mark.parametrize('hit', [False, True])
def test_intercepting_tap_real_reaction_reduces_pending_melee_hit_on_hit_or_miss(tmp_path,hit):
    # Counter attack uses its own sealed attack bonus. The incoming attack is
    # a weapon-damage packet with a +20 term; the rolled/committed difference
    # measures this one parked budget exactly.
    def attack_numbers(b):
        for a in b['action_catalog']:
            if a['source_definition_id'].endswith('.natural.unarmed_strike'):
                a['parameters']['typed']['numbers']['attack_bonus']=100 if hit else -100
            if a['display_name']=='Cause':
                a['parameters']['typed']['numbers']['attack_bonus']=100
                a['range_ft']=5
                a['parameters']['typed']['range_ft']=None
        for r in b.get('typed_reactions',[]):
            if r.get('feature_id')==P+'intercepting_tap':r['numbers']['attack_bonus']=100 if hit else -100
    cause=[{'type':'attack','attack_kind':'unarmed','on_hit':[{'type':'damage','flat':20,'damage_types':['bludgeoning'],'applies_to':'target'}]}]
    c,t,m=fight(tmp_path,[P+'intercepting_tap','PRESSURE_POINTS_BASE_NUMBING_POINT'],
        left_score=14,bundle_edit=attack_numbers,cause=cause,cause_target='HOSTILE_ENTITY')
    before=reload(c,m).state.actors[LEFT].current_hp
    turn(t,m,RIGHT)
    from tests.auto_worker1_support import resolve
    resolve(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    e=reload(c,m)
    packet=next(v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and LEFT in v.target_ids)
    assert packet.payload['rolled_or_pending_damage']-packet.payload['hp_damage']==(4 if hit else 1)
    assert e.state.actors[LEFT].current_hp==before-packet.payload['hp_damage']
    assert e.state.actors[LEFT].resources[FOCUS]==0
    counters=[v for v in e.events if v.event_type=='ATTACK_ROLLED' and v.source_definition_id==P+'intercepting_tap']
    assert len(counters)==1 and counters[0].payload['provisional_hit']==hit
    damage=[v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and RIGHT in v.target_ids]
    assert bool(damage)==hit
    marks=[v for v in e.events if v.event_type=='CONDITION_APPLIED' and RIGHT in v.target_ids and 'mark.' in v.payload.get('condition_id','')]
    assert len(marks)==int(hit)
    assert any(v.event_type=='REACTION_RESOLVED' and v.source_definition_id==P+'intercepting_tap' for v in e.events)


def test_stolen_step_mark_created_by_this_hits_rider_does_not_grant_half_speed(tmp_path):
    strike={'type':'attack','attack_kind':'unarmed','on_hit':[
        {'type':'mark','mark':'Pressure Point','applies_to':'target','duration':{'kind':'until_removed'}}]}
    def melee(b):
        for a in b['action_catalog']:
            if a['display_name']=='Marking strike':
                a['range_ft']=5
                a['parameters']['typed']['range_ft']=None
                a['parameters']['typed']['numbers']['attack_bonus']=100
    c,t,m=fight(tmp_path,[P+'stolen_pulse_step'],left_score=50,bundle_edit=melee,
        extra_actions=(('Marking strike',{'target_kind':'HOSTILE_ENTITY','effects':[strike]}),))
    settle(lambda a:act(t,m,'Touch the Point: Stolen Pulse Step',a))
    _,prompts=settle(lambda a:act(t,m,'Marking strike',a,target_id=RIGHT))
    e=reload(c,m)
    assert not any('half_speed' in [o['id'] for o in p.get('choice',{}).get('options',[])] for p in prompts)
    assert any('10 feet' in str(p) for p in prompts)
    assert not any('15 feet' in str(p) for p in prompts)


def test_heartbeats_bonus_on_a_confirmed_attack_without_normal_damage(tmp_path):
    strike={'type':'attack','attack_kind':'cultivation_melee','on_hit':[
        {'type':'condition','condition':'prone','applies_to':'target','duration':'until_removed'}]}
    def accuracy(b):
        for action in b['action_catalog']:
            if action['display_name']=='Silent strike':
                action['parameters']['typed']['numbers']['attack_bonus']=100
    c,t,m=fight(tmp_path,[P+'the_point_between_heartbeats'],cl=20,bundle_edit=accuracy,
        extra_actions=(('Silent strike',{'target_kind':'HOSTILE_ENTITY','effects':[strike]}),))
    settle(send_prefix(c,t,m,'The Point Between Heartbeats',target=RIGHT))
    settle(lambda a:act(t,m,'Silent strike',a,target_id=RIGHT))
    e=reload(c,m)
    assert not conditions(e,RIGHT,OPENING)
    bonus=[r for r in e.rolls if r.expression in {'6d10','6d10+0','12d10','12d10+0'}]
    assert len(bonus)==1
    assert e.state.actors[RIGHT].current_hp==1000-bonus[0].total
    assert conditions(e,RIGHT,'condition:typed.prone')


def test_life_gate_ai_cures_ally_and_leaves_poisoned_enemy_unchanged(tmp_path):
    poison=[{'type':'condition','condition':'poisoned','applies_to':'target','duration':'until_removed'}]
    c,t,m=fight(tmp_path,[P+'life_gate_touch'],ally=[],prepare=poison,prepare_target='ANY_CREATURE')
    settle(lambda a:act(t,m,'Prepare',a,target_id=ALLY))
    settle(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    settle(send_prefix(c,t,m,'Life Gate Touch',target=ALLY,ai=True),choose=option('end:'))
    e=reload(c,m)
    assert not conditions(e,ALLY,'condition:typed.poisoned')
    assert conditions(e,RIGHT,'condition:typed.poisoned')
    assert conditions(e,ALLY,USED+'life')
    assert not conditions(e,RIGHT,USED+'life')


def test_patient_hand_unused_check_bonus_expires_at_owner_next_end(tmp_path):
    c,t,m=fight(tmp_path,[P+'patient_hand'],prepare_target='SELF',
        prepare=[{'type':'temp_hp','applies_to':'self','flat':1}],prepare_costs=[(FOCUS,1)])
    settle(lambda a:act(t,m,'Prepare',a))
    settle(lambda a:act(t,m,'Dodge',a),choose=option(RIGHT))
    turn(t,m,RIGHT);turn(t,m,LEFT)
    assert conditions(reload(c,m),LEFT,PATIENT)
    turn(t,m,RIGHT)
    assert not conditions(reload(c,m),LEFT,PATIENT)


def test_meridian_field_ai_hinders_only_marked_enemies_not_marked_allies_or_neutrals(tmp_path):
    from tests.test_r4_integration import auto_candidate
    from combat.typed_executor import bears_mark
    witness='actor:factory.auto111-witness'
    c,t,m=fight(tmp_path,[P+'meridian_stillness_field'],right_team='team:neutral',
        ally=[],extra_witness=True,prepare_target='ANY_CREATURE',
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6},ALLY:{'x':2,'y':6}},
        prepare=[{'type':'mark','mark':'Pressure Point','applies_to':'target','duration':{'kind':'until_removed'}}])
    for who in (RIGHT,ALLY,witness):settle(lambda a:act(t,m,'Prepare',a,target_id=who))
    e=reload(c,m)
    candidate=next(k for k in e.legal_candidates() if k.display_name.startswith('Meridian Stillness Field')
        and k.destination is not None and (k.destination.x,k.destination.y)==(4,6))
    auto_candidate(c,m,LEFT,candidate.candidate_id)
    settle(lambda a:t.auto_step(m,t.state(m)['last_sequence'],a))
    e=reload(c,m)
    assert all(bears_mark(e.state.actors[who],LEFT,'Pressure Point') for who in (RIGHT,ALLY,witness))
    assert e._effective_speed(e.state.actors[witness])==20
    assert e._effective_speed(e.state.actors[ALLY])==30
    assert e._effective_speed(e.state.actors[RIGHT])==30
