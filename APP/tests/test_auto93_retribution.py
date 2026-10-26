"""Chosen physical packets and retained Counterstrike/pressure next-end expiry at the table."""
import pytest
from combat.ext.retribution_riders import DUG_IN
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, action_sender
from tests.hunt15_support import turn

BASE = 'RETRIBUTION_BASE_COUNTERSTRIKE'
DUG = 'TAL_RETRIBUTION_DUG_IN_BLOW'
HOOK = 'TAL_RETRIBUTION_TERRIFYING_HOOK'
PRESSURE = 'TAL_RETRIBUTION_VIOLENT_PRESSURE'
DAO = {'items': [{'item_id': 'tianxia.mortal.weapon.dao', 'name': 'Dao', 'quantity': 1}]}


def settle(send, choose=None):
    answers, prompts = [], []
    for _ in range(24):
        result = send(answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return result, prompts
        p = result['reaction']; prompts.append(p)
        chosen = (choose or picker)(p)
        # Ready asks Use/Decline without option buttons; a native Use is intentional.
        selection = 'USE' if chosen or not p.get('choice') else 'DECLINE'
        answers.append({**p['context'], 'selection': selection, 'option_ids': chosen})
    raise AssertionError('too many choices')


def fixture(tmp_path, talent, *, legacy=False, right_score=14, miss=False, packets=('slashing',)*3, extra_protection=False):
    def seal(bundle):
        for action in bundle['action_catalog']:
            typed = action.get('parameters', {}).get('typed', {})
            if action['display_name'] == 'Cause':
                action['economy'] = 'ACTION'  # real accepted hostile Action triggers the preparation
            if typed.get('weapon'):
                typed.setdefault('numbers', {})['attack_bonus'] = -100 if miss else 100
            if legacy:
                def walk(x):
                    if isinstance(x, dict):
                        x.pop('choose_instance', None)
                        if x.get('type') == 'condition' and x.get('condition') == 'frightened':
                            x['duration'] = 'special'
                        for v in x.values(): walk(v)
                    elif isinstance(x, list):
                        for v in x: walk(v)
                walk(typed)
    return fight(tmp_path, [BASE, talent, 'TAL_RETRIBUTION_REFLEXIVE_PREPARATION'], left_kit=DAO, right_score=right_score,
        prepare=[{'type': 'retribution_dug_in', 'applies_to': 'target', 'choose_instance': True}] if extra_protection else [],
        cause=[{'type': 'damage', 'flat': 9, 'damage_types': [k], 'applies_to': 'target'} for k in packets],
        bundle_edit=seal)


def picker(p):
    if p['context']['reaction_source_id'] == 'choice:needle.counterstrike':
        return [next(o['id'] for o in p['choice']['options'] if 'a foe starts an action that targets you' in o['label'] and 'Dao' in o['label'])]
    return [o['id'] for o in (p.get('choice') or {}).get('options', [])][:1]


def prepare(c, t, m, name):
    def select(p):
        if p['context']['reaction_source_id'] == 'choice:needle.counterstrike':
            return [next(o['id'] for o in p['choice']['options'] if o['label'].startswith(name+' (') and 'Dao' in o['label'] and 'a foe starts an action that targets you' in o['label'])]
        return picker(p)
    settle(lambda a: act(t, m, 'Reflexive Preparation', a), select)
    turn(t, m, RIGHT)


def damage(e):
    return [x.payload['reduced_to'] for x in e.events if x.event_type == 'DAMAGE_COMMITTED' and x.target_ids == (LEFT,)]


@pytest.mark.parametrize('mode', ['manual', 'enemy_ai', 'owner_ai', 'legacy'])
def test_dug_in_can_skip_first_packet_choose_second_and_is_used_once(tmp_path, mode):
    c, t, m = fixture(tmp_path, DUG, legacy=mode == 'legacy')
    prepare(c, t, m, 'Counterstrike + Dug-In Blow')
    if mode == 'owner_ai': c.set_controller_mode(m, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    count = []
    def pick(p):
        if p['context']['reaction_source_id'] == 'choice:needle.dug_in_instance':
            count.append(p)
            return [] if len(count) == 1 else ['resist']
        return picker(p)
    _, prompts = settle(action_sender(c, t, m, 'Cause', ai=mode == 'enemy_ai', target_id=LEFT), pick)
    e = reload(c, m)
    assert damage(e) == ([9, 4, 9] if mode in ('manual', 'enemy_ai') else [4, 9, 9])
    assert not any(h.condition_id == DUG_IN for h in e.state.actors[LEFT].conditions.values())
    assert e.state.actors[LEFT].reaction_available  # choosing the instance costs no Reaction
    if mode in ('manual', 'enemy_ai'):
        assert len(count) == 2
        assert all('Visitor' in str(p) and 'Cause' in str(p) and 'Keeper' in str(p) and 'No extra cost' in str(p) for p in count)
    if mode == 'legacy': assert not count
    assert len([x for x in e.events if x.event_type == 'ATTACK_ROLLED' and x.actor_id == LEFT]) == 1


@pytest.mark.parametrize('packets', [('fire', 'slashing', 'force'), ('slashing',)*3])
def test_dug_in_decline_preserves_until_actual_owner_next_start(tmp_path, packets):
    c, t, m = fixture(tmp_path, DUG, packets=packets)
    prepare(c, t, m, 'Counterstrike + Dug-In Blow')
    seen = []
    def decline(p):
        if p['context']['reaction_source_id'] == 'choice:needle.dug_in_instance':
            seen.append(p); return []
        return picker(p)
    settle(lambda a: act(t, m, 'Cause', a, target_id=LEFT), decline)
    e = reload(c, m)
    assert damage(e) == [9]*3
    held = next(x for x in e.state.actors[LEFT].conditions.values() if x.condition_id == DUG_IN)
    assert held.data['choose_instance'] == 1 and held.data['from'] == RIGHT
    assert len(seen) == sum(k in ('slashing', 'piercing', 'bludgeoning') for k in packets)
    turn(t, m, LEFT)
    assert not any(x.condition_id == DUG_IN for x in reload(c, m).state.actors[LEFT].conditions.values())


def test_consuming_one_dug_in_instance_keeps_a_second_held_protection(tmp_path):
    c, t, m = fixture(tmp_path, DUG, extra_protection=True)
    # Evented setup supplies a second protection before an actual Counter grants its own.
    settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), picker)
    assert sum(x.condition_id == DUG_IN for x in reload(c, m).state.actors[LEFT].conditions.values()) == 1
    prepare(c, t, m, 'Counterstrike + Dug-In Blow')
    _, prompts = settle(lambda a: act(t, m, 'Cause', a, target_id=LEFT), picker)
    e = reload(c, m)
    assert damage(e) == [4, 4, 9]
    assert len([p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.dug_in_instance']) == 2
    assert not any(x.condition_id == DUG_IN for x in e.state.actors[LEFT].conditions.values())


@pytest.mark.parametrize('miss', [True, False])
def test_dug_in_is_not_asked_without_this_owned_successful_counter(tmp_path, miss):
    c, t, m = fixture(tmp_path, DUG if miss else HOOK, miss=miss)
    prepare(c, t, m, 'Counterstrike + '+('Dug-In Blow' if miss else 'Terrifying Hook'))
    _, prompts = settle(lambda a: act(t, m, 'Cause', a, target_id=LEFT), picker)
    e = reload(c, m)
    assert damage(e) == [9]*3
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.dug_in_instance' for p in prompts)


@pytest.mark.parametrize('case', ['fail', 'success', 'legacy'])
def test_terrifying_hook_native_fear_ends_at_recipient_next_end(tmp_path, case):
    c, t, m = fixture(tmp_path, HOOK, right_score=214 if case == 'success' else 14, legacy=case == 'legacy')
    prepare(c, t, m, 'Counterstrike + Terrifying Hook')
    settle(lambda a: act(t, m, 'Cause', a, target_id=LEFT), picker)
    e = reload(c, m)
    feared = lambda eng: any(x.condition_id.endswith('.frightened') for x in eng.state.actors[RIGHT].conditions.values())
    assert feared(e) == (case != 'success')
    saves = [x for x in e.events if x.event_type == 'SAVE_ROLLED' and x.actor_id == RIGHT]
    assert len(saves) == 1 and saves[0].payload['success'] == (case == 'success')
    turn(t, m, LEFT)
    # It was hit during its current turn. Its *next* actual turn must still be affected.
    assert feared(reload(c, m)) == (case != 'success')
    turn(t, m, RIGHT)
    assert feared(reload(c, m)) == (case != 'success')
    turn(t, m, LEFT)
    assert not feared(reload(c, m))


@pytest.mark.parametrize('ai', [False, True])
def test_violent_pressure_native_fear_survives_start_and_ends_next_end(tmp_path, ai):
    c, t, m = fixture(tmp_path, PRESSURE)
    # Source timing/rest admission is explicitly blocked in the report; exercise its actual Bonus Action row.
    settle(action_sender(c, t, m, 'Violent Pressure', ai=ai, target_id=RIGHT), picker)
    e = reload(c, m)
    assert not e.state.actors[LEFT].bonus_action_available
    assert any(x.condition_id.endswith('.frightened') for x in e.state.actors[RIGHT].conditions.values())
    if ai: c.set_controller_mode(m, actor_id=LEFT, controller_mode='MANUAL')
    turn(t, m, RIGHT)
    assert any(x.condition_id.endswith('.frightened') for x in reload(c, m).state.actors[RIGHT].conditions.values())
    turn(t, m, LEFT)
    assert not any(x.condition_id.endswith('.frightened') for x in reload(c, m).state.actors[RIGHT].conditions.values())
