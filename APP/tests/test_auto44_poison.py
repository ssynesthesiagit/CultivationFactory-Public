"""Poison choices, actual hit/save budgets and persisted native flight."""
from copy import deepcopy
import json
from tests.h1_support import ROOT
import pytest
from combat import flight
from combat.ext import poison
from combat.ext.stacking_marks import count
from combat.typed_executor import condition_rules
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, action_sender
from tests.auto_worker1_stars_support import resolve, turn, cell_send, ascend
P = 'tianxia.talent.poison.'
D = poison.DELIVER
POOL = 'resource:core.qi'
MIASMA = P+'miasma_form'
STRIKE = P+'venomous_strike'

def delivery_effects():
    return deepcopy(json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics'][D]['effects'])

def blocked(e, aid):
    return any((r.get('no_reactions') for r in condition_rules(e.state.actors[aid])))

def paid(e, s):
    return [v.payload['amount'] for v in e.events if v.event_type == 'RESOURCE_SPENT' and v.source_definition_id == s]

@pytest.mark.parametrize('source,label,speed,cost', [(MIASMA, 'Miasma Form', 30, 5), (poison.SOVEREIGN, 'Venom-Sovereign Incarnation', 40, 10)])
@pytest.mark.parametrize('ai', [False, True])
def test_active_flight(tmp_path, source, label, speed, cost, ai):
    c, t, m = fight(tmp_path, [source], cl=17)
    e = reload(c, m)
    assert flight.profile(e, e.state.actors[LEFT]).speed_ft == 0
    resolve(action_sender(c, t, m, label, ai=ai))
    e = reload(c, m)
    a = e.state.actors[LEFT]
    assert flight.profile(e, a).speed_ft == speed and flight.profile(e, a).hover
    assert e._effective_speed(a) == 30 and a.resources[POOL] == 100 - cost
    if not ai:
        assert ascend(c, t, m, LEFT)['status'] == 'COMMITTED'
        assert reload(c, m).state.actors[LEFT].position.z == 1

@pytest.mark.parametrize('failed', [False, True])
@pytest.mark.parametrize('ai,accept', [(False, False), (False, True), (True, True)])
def test_numbing_final_save_choice_and_expiry(tmp_path, failed, ai, accept):
    c, t, m = fight(tmp_path, [D, P + 'numbing_dose'], left_attack_bonus=100, left_save_dc=100 if failed else -100)
    _, prompts = resolve(action_sender(c, t, m, 'Deliver the Dose', ai=ai, target_id=RIGHT), {'choice:needle.poison_numbing': ['APPLY'] if accept else []})
    e = reload(c, m)
    assert e._effective_speed(e.state.actors[RIGHT]) == 30 - ((10 if failed else 5) if accept else 0)
    assert blocked(e, RIGHT) == (accept and failed) and e.state.actors[LEFT].resources[POOL] == 100 - int(accept)
    if not ai:
        assert any(('Numbing Dose' in str(p) and 'Visitor' in str(p) and (p.get('cost') == '1 Qi') for p in prompts))
    if ai:
        c.set_controller_mode(m, actor_id=LEFT, controller_mode='MANUAL')
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    e = reload(c, m)
    assert e._effective_speed(e.state.actors[RIGHT]) == 30 and (not blocked(e, RIGHT))

@pytest.mark.parametrize('payment', [False, True])
def test_paralytic_actual_payment_discount(tmp_path, payment):
    c, t, m = fight(tmp_path, [D, P + 'paralytic_dose'], prepare=delivery_effects(), prepare_source=D, prepare_attack_bonus=100, prepare_costs=[(POOL, 1)] if payment else (), left_attack_bonus=100)
    resolve(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    e = reload(c, m)
    assert e._effective_speed(e.state.actors[RIGHT]) == 0 and blocked(e, RIGHT)
    assert any((r.get('save_mode', {}).get('DEX') == 'DISADVANTAGE' for r in condition_rules(e.state.actors[RIGHT])))
    assert paid(e, P + 'paralytic_dose') == [1 if payment else 2] and e.state.actors[LEFT].resources[POOL] == 98
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    e = reload(c, m)
    assert e._effective_speed(e.state.actors[RIGHT]) == 30

def test_success_has_no_paralytic_offer(tmp_path):
    c, t, m = fight(tmp_path, [D, P + 'paralytic_dose'], left_attack_bonus=100, left_save_dc=-100)
    _, prompts = resolve(lambda a: act(t, m, 'Deliver the Dose', a, target_id=RIGHT))
    assert not any(('Paralytic Dose' in str(p) for p in prompts))
    assert reload(c, m).state.actors[LEFT].resources[POOL] == 100

def test_delivery_once_per_turn_and_next_check(tmp_path):
    check = {'type': 'skill_check', 'ability': 'wis', 'skill': 'Perception', 'applies_to': 'self'}
    c, t, m = fight(tmp_path, [D], prepare=delivery_effects(), prepare_source=D, prepare_attack_bonus=100, cause=[{'type': 'rider_targets', 'range_ft': 0, 'count': 1, 'minimum': 1, 'requires_visibility': False, 'effects': [check, check]}], cause_target='SELF', left_attack_bonus=100)
    resolve(lambda a: act(t, m, 'Deliver the Dose', a, target_id=RIGHT))
    resolve(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    e = reload(c, m)
    assert len([v for v in e.events if v.event_type == 'SAVE_ROLLED' and v.actor_id == RIGHT]) == 1
    assert len([v for v in e.events if v.event_type == 'DAMAGE_COMMITTED' and RIGHT in v.target_ids]) == 2
    assert count(e, e.state.actors[LEFT], e.state.actors[RIGHT], 'Dose Mark') == 1
    turn(t, m, RIGHT)
    resolve(lambda a: act(t, m, 'Cause', a))
    e = reload(c, m)
    checks = [v for v in e.events if v.event_type == 'CHECK_ROLLED' and v.actor_id == RIGHT]
    assert [v.payload['actor']['mode'] for v in checks] == ['DISADVANTAGE', 'NORMAL']
    assert not any((v.condition_id == poison.NEXT_CHECK for v in e.state.actors[RIGHT].conditions.values()))

@pytest.mark.parametrize('cl,dice', [(1, 1), (11, 2), (17, 3)])
@pytest.mark.parametrize('ai,accept', [(False, False), (False, True), (True, True)])
def test_strike_paid_hit_scaling_and_target_expiry(tmp_path, cl, dice, ai, accept):
    c, t, m = fight(tmp_path, [D, STRIKE], cl=cl, left_attack_bonus=100)
    _, prompts = resolve(action_sender(c, t, m, 'Deliver the Dose', ai=ai, target_id=RIGHT), {'choice:needle.venomous_strike': ['STRIKE'] if accept else []})
    e = reload(c, m)
    assert paid(e, STRIKE) == ([1] if accept else [])
    assert len([v for v in e.events if v.event_type == 'SAVE_ROLLED' and v.source_definition_id == STRIKE]) == int(accept)
    packets = [v for v in e.events if v.event_type == 'DAMAGE_COMMITTED' and v.payload.get('display_source_id') == STRIKE]
    assert len(packets) == int(accept)
    if packets:
        assert packets[0].payload['hp_damage'] > 0
    if not ai:
        assert any((f'{dice}d6' in str(p) for p in prompts))
    if ai:
        c.set_controller_mode(m, actor_id=LEFT, controller_mode='MANUAL')
    turn(t, m, RIGHT)
    assert not any((v.condition_id == 'condition:typed.poisoned' for v in reload(c, m).state.actors[RIGHT].conditions.values()))

@pytest.mark.parametrize('flag,loss', [(True, 10), (False, 20), (None, 20)])
def test_miasma_nonmagical_classification(tmp_path, flag, loss):
    d = {'type': 'damage', 'flat': 20, 'damage_types': ['bludgeoning'], 'applies_to': 'target'}
    if flag is not None:
        d['mundane'] = flag
    c, t, m = fight(tmp_path, [MIASMA], cause=[d])
    resolve(lambda a: act(t, m, 'Miasma Form', a))
    turn(t, m, RIGHT)
    resolve(lambda a: act(t, m, 'Cause', a, target_id=LEFT))
    assert reload(c, m).state.actors[LEFT].current_hp == 1000 - loss

def test_miasma_concentration_ends_flight(tmp_path):
    c, t, m = fight(tmp_path, [MIASMA], cause=[{'type': 'condition', 'condition': 'stunned', 'applies_to': 'target', 'duration': 'until_removed'}])
    resolve(lambda a: act(t, m, 'Miasma Form', a))
    turn(t, m, RIGHT)
    resolve(lambda a: act(t, m, 'Cause', a, target_id=LEFT))
    e = reload(c, m)
    assert e.state.actors[LEFT].concentration is None and flight.profile(e, e.state.actors[LEFT]).speed_ft == 0

@pytest.mark.parametrize('failed', [False, True])
def test_dust_actual_recipient_choice_and_expiry(tmp_path, failed):
    c, t, m = fight(tmp_path, [P + 'irritating_dust'], left_save_dc=100 if failed else -100, positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 6, 'y': 6}})
    _, prompts = resolve(cell_send(t, m, 'Irritating Dust', (4, 6)), {'choice:needle.area_recipients': [RIGHT]})
    e = reload(c, m)
    assert blocked(e, RIGHT) and (not blocked(e, LEFT))
    assert [v.actor_id for v in e.events if v.event_type == 'SAVE_ROLLED'] == [RIGHT]
    assert e.state.actors[LEFT].resources[POOL] == 99 and any((LEFT in str(p) and RIGHT in str(p) for p in prompts))
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    assert not blocked(reload(c, m), RIGHT)

def test_unowned_followups_inert(tmp_path):
    c, t, m = fight(tmp_path, [D], left_attack_bonus=100)
    _, prompts = resolve(lambda a: act(t, m, 'Deliver the Dose', a, target_id=RIGHT))
    e = reload(c, m)
    assert not prompts and e.state.actors[LEFT].resources[POOL] == 100 and (flight.profile(e, e.state.actors[LEFT]).speed_ft == 0)

@pytest.mark.parametrize('ai,accept', [(False, False), (True, True)])
def test_paralytic_decline_and_automatic_choice(tmp_path, ai, accept):
    c, t, m = fight(tmp_path, [D, P + 'paralytic_dose'], left_attack_bonus=100)
    resolve(action_sender(c, t, m, 'Deliver the Dose', ai=ai, target_id=RIGHT), {'choice:needle.poison_paralytic': ['APPLY'] if accept else []})
    e = reload(c, m)
    assert e._effective_speed(e.state.actors[RIGHT]) == (0 if accept else 30)
    assert paid(e, P + 'paralytic_dose') == ([2] if accept else [])

def test_separate_numbing_payment_does_not_discount_paralytic(tmp_path):
    c, t, m = fight(tmp_path, [D, P + 'numbing_dose', P + 'paralytic_dose'], left_attack_bonus=100)
    resolve(lambda a: act(t, m, 'Deliver the Dose', a, target_id=RIGHT))
    e = reload(c, m)
    assert paid(e, P + 'numbing_dose') == [1] and paid(e, P + 'paralytic_dose') == [2]
    assert e.state.actors[LEFT].resources[POOL] == 97

def test_strike_only_one_actual_hit_each_turn(tmp_path):
    c, t, m = fight(tmp_path, [D, STRIKE], prepare=delivery_effects(), prepare_source=D, prepare_attack_bonus=100, left_attack_bonus=100)
    resolve(lambda a: act(t, m, 'Deliver the Dose', a, target_id=RIGHT))
    resolve(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    e = reload(c, m)
    assert paid(e, STRIKE) == [1]
    assert len([v for v in e.events if v.event_type == 'DAMAGE_COMMITTED' and RIGHT in v.target_ids]) == 3

def test_miasma_qualified_grapple_escape(tmp_path):
    c, t, m = fight(tmp_path, [MIASMA], cause=[{'type': 'condition', 'condition': 'grappled', 'applies_to': 'target', 'until_escape': True}])
    resolve(lambda a: act(t, m, 'Miasma Form', a))
    turn(t, m, RIGHT)
    resolve(lambda a: act(t, m, 'Cause', a, target_id=LEFT))
    turn(t, m, LEFT)
    resolve(lambda a: act(t, m, 'Escape grapple', a))
    e = reload(c, m)
    assert next((v for v in reversed(e.events) if v.event_type == 'CHECK_ROLLED')).payload['actor']['mode'] == 'ADVANTAGE'

@pytest.mark.parametrize('ai', [False, True])
def test_deepen_requires_two_actual_owned_marks_and_ai_can_use_it(tmp_path, ai):
    c, t, m = fight(tmp_path, [poison.DEEPEN], prepare=[{'type': 'mark', 'mark': 'Dose Mark', 'applies_to': 'target', 'duration': {'kind': 'until_removed'}}])
    resolve(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    assert not any((g['label'] == 'Deepen the Burden' for g in t.state(m)['menu']['actions']))
    resolve(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    resolve(action_sender(c, t, m, 'Deepen the Burden', ai=ai, target_id=RIGHT))
    e = reload(c, m)
    assert count(e, e.state.actors[LEFT], e.state.actors[RIGHT], 'Dose Mark') == 0
    assert count(e, e.state.actors[LEFT], e.state.actors[RIGHT], 'Toxin Burden') == 1
    assert e.state.actors[LEFT].resources[POOL] == 99

def test_successful_strike_penalty_ends_at_target_start(tmp_path):
    c, t, m = fight(tmp_path, [D, STRIKE], left_attack_bonus=100, left_save_dc=-100)
    resolve(lambda a: act(t, m, 'Deliver the Dose', a, target_id=RIGHT))
    e = reload(c, m)
    held = next((v for v in e.state.actors[RIGHT].conditions.values() if v.condition_id == poison.NEXT_CHECK))
    assert held.expires_on.startswith('START_OF_TURN_AT:' + RIGHT + ':')
    turn(t, m, RIGHT)
    assert not any((v.condition_id == poison.NEXT_CHECK for v in reload(c, m).state.actors[RIGHT].conditions.values()))

def test_dust_automatic_caster_selects_actual_hostile_recipient(tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter
    c, t, m = fight(tmp_path, [P + 'irritating_dust'], positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 6, 'y': 6}})
    menu = t.state(m)['menu']
    cid = next((o['candidate_id'] for g in menu['actions'] if g['label'] == 'Irritating Dust' for o in g['options'] if o.get('destination') == {'x': 4, 'y': 6}))
    real = c.controller

    class Controller:

        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)
    c.controller = Controller()
    c.set_controller_mode(m, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    _, prompts = resolve(lambda a: t.auto_step(m, t.state(m)['last_sequence'], a))
    e = reload(c, m)
    assert not prompts and blocked(e, RIGHT) and (not blocked(e, LEFT))
    assert [v.actor_id for v in e.events if v.event_type == 'SAVE_ROLLED'] == [RIGHT]


@pytest.mark.parametrize('cl,dice', [(10,2),(15,3)])
def test_strike_at_exact_tianxia_realm_boundaries(tmp_path,cl,dice):
    c,t,m=fight(tmp_path,[D,STRIKE],cl=cl,left_attack_bonus=100)
    _,prompts=resolve(lambda a:act(t,m,'Deliver the Dose',a,target_id=RIGHT))
    e=reload(c,m)
    assert paid(e,STRIKE)==[1]
    assert any(f'{dice}d6' in str(p) for p in prompts)
    assert any(v.event_type=='DAMAGE_ROLLED' and v.payload.get('display_source_id')==STRIKE and str(v.payload.get('expression')).startswith(f'{dice}d6') and len(v.payload['dice'])==dice for v in e.events)
