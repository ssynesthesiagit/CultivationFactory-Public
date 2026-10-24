"""Earth Round 2 actual combat decisions, defensive windows and persistence."""
import pytest
from combat.ext import elements_earth as blade, earth_responses as earth
from combat.typed_executor import bears_mark
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload, turn, action_sender

CLOD = 'EARTH_BASE_WEIGHT_SEEKING_CLOD'
WEIGHT = 'TAL_EARTH_WEIGHT_SEAL_STRIKE'
MULE = 'TAL_EARTH_MULE_SHOULDER_METHOD'
DAGGER = 'weapon.bi_shou'  # the starting kit's dagger, which both fixture creatures carry


@pytest.mark.parametrize('choice', ['SPEED', 'JUMP', 'CHECK'])
def test_weight_seal_options_commit_and_expire(tmp_path, choice):
    combat, table, mid = fight(tmp_path, [CLOD, WEIGHT], left_score=30, right_score=14, left_attack_bonus=100)
    send = action_sender(combat, table, mid, CLOD, target_id=RIGHT)
    result = send([])
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert 'Weight-Seal Strike' in str(prompt) and 'Visitor' in str(prompt)
    assert send([{**prompt['context'], 'selection': 'USE', 'option_ids': [choice]}])['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    target = engine.state.actors[RIGHT]
    assert bears_mark(target, LEFT, 'Burden Mark')
    if choice == 'SPEED':
        assert engine._effective_speed(target) == 25
    else:
        cid = 'condition:typed.earth_no_jump' if choice == 'JUMP' else earth.WEIGHT_CHECK
        assert any(c.condition_id == cid for c in target.conditions.values())
        if choice == 'JUMP':
            from combat.posture import allows_jumping
            assert not allows_jumping(target)
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 30
    assert not any(c.source_definition_id == WEIGHT for c in engine.state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize('condition', ['prone', 'grappled', 'mark'])
def test_mule_shoulder_ignores_one_earth_condition_only(tmp_path, condition):
    effect = ({'type': 'mark', 'mark': 'Burden Mark', 'applies_to': 'target', 'duration': {'kind': 'until_removed'}}
              if condition == 'mark' else {'type': 'condition', 'condition': condition, 'applies_to': 'target', 'duration': 'until_removed'})
    combat, table, mid = fight(tmp_path, right_talents=[MULE],
        talents=['TAL_EARTH_DEEP_ROOT_STANCE'],
        prepare_source='TAL_EARTH_EARTHBIND_LINE', prepare=[effect])
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert not any(c.condition_id.endswith('.' + condition) for c in engine.state.actors[RIGHT].conditions.values())
    if condition == 'mark':
        assert not bears_mark(engine.state.actors[RIGHT], LEFT, 'Burden Mark')
    assert engine.state.actors[RIGHT].turn_flags['_round_mule_shoulder_used'] == 1
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    if condition == 'mark':
        assert bears_mark(engine.state.actors[RIGHT], LEFT, 'Burden Mark')
    else:
        assert any(c.condition_id.endswith('.' + condition) for c in engine.state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize('ai,accept', [(False, True), (False, False), (True, True)])
@pytest.mark.parametrize('feature,activation,name', [
    ('TAL_EARTH_DEEP_ROOT_STANCE', 'Deep Root Stance', 'Deep Root Stance'),
    ('TAL_EARTH_MOUNTAIN_ROOT_BODY', 'Dodge', 'Mountain-Root Body')])
def test_earth_missed_attack_mark_is_owners_choice(tmp_path, ai, accept, feature, activation, name):
    combat, table, mid = fight(tmp_path, [feature], prepare_target='SELF',
        prepare=[{'type': 'ac_bonus', 'flat': 1000, 'applies_to': 'self', 'duration': 'until_removed'}])
    assert act(table, mid, 'Prepare')['status'] == 'COMMITTED'
    assert act(table, mid, activation)['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    if ai:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    send = action_sender(combat, table, mid, 'Unarmed Strike', target_id=LEFT)
    result = send([])
    if not ai:
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        assert name in str(prompt) and 'Visitor' in str(prompt)
        result = send([{**prompt['context'], 'selection': 'USE' if accept else 'DECLINE',
            'option_ids': ['MARK'] if accept else []}])
    assert result['status'] == 'COMMITTED', result
    assert bears_mark(reload(combat, mid).state.actors[RIGHT], LEFT, 'Burden Mark') == accept



@pytest.mark.parametrize('owned,ai,accept', [(False, False, False), (True, False, True), (True, False, False), (True, True, True)])
def test_burden_the_blade_exact_hit_physical_resistance(tmp_path, owned, ai, accept):
    # A real compiled unarmed attack has fixed physical damage: roll RNG is identical
    # across owned/unowned/declined runs because the response itself rolls no dice.
    combat, table, mid = fight(tmp_path, [blade.FEATURE] if owned else [], left_score=2, right_score=30,
        cause=[{'type': 'damage', 'flat': 7, 'damage_type': 'FORCE', 'applies_to': 'target'}],
        prepare=[{'type': 'mark', 'mark': 'Burden Mark', 'applies_to': 'target', 'duration': {'kind': 'until_removed'}}])
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    if ai:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    send = action_sender(combat, table, mid, 'Unarmed Strike', target_id=LEFT)
    result = send([])
    if owned and not ai:
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        assert 'Burden the Blade' in str(prompt)
        result = send([{**prompt['context'], 'selection': 'USE' if accept else 'DECLINE',
                       'option_ids': ['SPEND'] if accept else []}])
    assert result['status'] == 'COMMITTED', result
    engine = reload(combat, mid)
    damage = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and LEFT in e.target_ids)
    rolled = damage.payload['rolled_or_pending_damage']
    assert damage.payload['reduced_to'] == (rolled // 2 if owned and accept else rolled)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, 'Burden Mark') == (not (owned and accept))
    assert bool([c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id == blade.HEAVY]) == (owned and accept)
    assert not any(e.event_type == 'GM_RIDER' and 'Burden the Blade' in str(e.payload) for e in engine.events)
    before = engine.state.actors[LEFT].current_hp
    assert act(table, mid, 'Cause', target_id=LEFT)['status'] == 'COMMITTED'
    assert reload(combat, mid).state.actors[LEFT].current_hp == before - 7
    turn(table, mid, LEFT)
    if ai:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='MANUAL')
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Unarmed Strike', target_id=LEFT)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    rolled_attack = next(e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED')
    assert rolled_attack.payload['mode'] == ('DISADVANTAGE' if owned and accept else 'NORMAL')
    assert not any(c.condition_id == blade.HEAVY for c in engine.state.actors[RIGHT].conditions.values())


def test_burden_the_blade_heavy_penalty_waits_for_its_own_attack(tmp_path):
    """"Its next attack with the same weapon or limb has disadvantage": being attacked is not that attack.

    Both creatures here carry the same Bi Shou Dagger, so the penalty they each hold names the
    weapon the other one is swinging: a cleanup that reads the target as well as the attacker would
    spend the defender's pending penalty when its own side merely hit it."""
    combat, table, mid = fight(tmp_path, [blade.FEATURE], left_score=2, right_score=30,
        prepare=[{'type': 'mark', 'mark': 'Burden Mark', 'applies_to': 'target',
                  'duration': {'kind': 'until_removed'}}])
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    send = action_sender(combat, table, mid, DAGGER, target_id=LEFT)
    prompt = send([])['reaction']
    assert 'Burden the Blade' in str(prompt)
    assert send([{**prompt['context'], 'selection': 'USE', 'option_ids': ['SPEND']}])['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    heavy = [c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id == blade.HEAVY]
    assert heavy, 'the attack that was answered carries the penalty forward'
    dagger = next(row for row in engine.action_catalog.values()
                  if row.source_definition_id.endswith(DAGGER) and row.owner_id == RIGHT)
    assert heavy[0].data['weapon'] == dagger.source_definition_id, \
        'the printed penalty names the weapon, not the action that swung it'
    turn(table, mid, LEFT)
    assert act(table, mid, DAGGER, target_id=RIGHT)['status'] == 'COMMITTED'
    assert [c for c in reload(combat, mid).state.actors[RIGHT].conditions.values() if c.condition_id == blade.HEAVY], \
        'being attacked with the same weapon does not spend the holder pending penalty'
    turn(table, mid, RIGHT)
    assert act(table, mid, DAGGER, target_id=LEFT)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    rolled_attack = next(e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED')
    assert rolled_attack.payload['mode'] == 'DISADVANTAGE', 'and the holder next swing is the one that pays'
    assert not any(c.condition_id == blade.HEAVY for c in engine.state.actors[RIGHT].conditions.values())



def cell_action(combat, table, mid, source, x, y, answers=()):
    state = table.state(mid)
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.destination is not None
        and c.destination.x == x and c.destination.y == y
        and (c.source_definition_id.endswith(source) if source != 'move' else c.source_definition_id == 'system:combat.movement'))
    menu = state['menu']
    answers = list(answers)
    for _ in range(5):
        result = table.act(mid, candidate.candidate_id, menu['decision_id'], menu['state_version'], state['last_sequence'], answers)
        if result['status'] != 'REACTION_REQUIRED' or 'Set Foundation' not in str(result['reaction']):
            return result
        # Decline the separate crossing mark so it cannot mask the memory mark.
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE', 'option_ids': []})
    raise AssertionError('Repeated Set Foundation decision')


@pytest.mark.parametrize('owns', [False, True])
def test_foundation_remembers_second_entry_after_reload(tmp_path, owns):
    talents = ['EARTH_BASE_SET_FOUNDATION', *([earth.REMEMBERS] if owns else [])]
    combat, table, mid = fight(tmp_path, talents)
    assert act(table, mid, 'EARTH_BASE_SET_FOUNDATION', target_id=LEFT)['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    assert cell_action(combat, table, mid, 'move', 3, 7)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert bool([c for c in engine.state.actors[LEFT].conditions.values() if c.condition_id == earth.VISITS]) == owns
    result = cell_action(combat, table, mid, 'move', 4, 7)
    if result['status'] == 'REACTION_REQUIRED':
        prompt = result['reaction']
        assert 'Set Foundation' in str(prompt), result
        result = cell_action(combat, table, mid, 'move', 4, 7,
            [{**prompt['context'], 'selection': 'DECLINE', 'option_ids': []}])
    assert result['status'] == 'COMMITTED', result
    result = cell_action(combat, table, mid, 'move', 3, 7)
    if owns:
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        assert 'Buried Foundation Remembers' in str(prompt)
        result = cell_action(combat, table, mid, 'move', 3, 7,
            [{**prompt['context'], 'selection': 'USE', 'option_ids': ['MARK']}])
    assert result['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, 'Burden Mark') == owns


def test_weight_seal_next_shove_check_consumes_once(tmp_path):
    combat, table, mid = fight(tmp_path, [CLOD, WEIGHT], left_score=30, left_attack_bonus=100,
        cause_name='Shove (check)', cause=[{'type': 'contest_against',
            'actor_check': {'kind': 'check', 'ability': 'STR', 'skill': 'Athletics'},
            'target_check': {'kind': 'check', 'ability': 'DEX', 'skill': 'Acrobatics'},
            'on_success': [], 'on_fail': []}])
    send = action_sender(combat, table, mid, CLOD, target_id=RIGHT)
    prompt = send([])['reaction']
    assert send([{**prompt['context'], 'selection': 'USE', 'option_ids': ['CHECK']}])['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Shove (check)', target_id=LEFT)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    rolled = next(e for e in reversed(engine.events) if e.event_type == 'CHECK_ROLLED')
    assert rolled.payload['actor']['mode'] == 'DISADVANTAGE'
    assert not any(c.condition_id == earth.WEIGHT_CHECK for c in engine.state.actors[RIGHT].conditions.values())
    assert act(table, mid, 'Shove (check)', target_id=LEFT)['status'] == 'COMMITTED'
    rolled = next(e for e in reversed(reload(combat, mid).events) if e.event_type == 'CHECK_ROLLED')
    assert rolled.payload['actor']['mode'] == 'NORMAL'


def test_earthbind_line_is_a_foundation_after_commit(tmp_path):
    combat, table, mid = fight(tmp_path, ['TAL_EARTH_EARTHBIND_LINE'])
    assert act(table, mid, 'Earthbind Line')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    zone = next(z for z in engine.state.zones.values() if z.active and z.source_definition_id.endswith('EARTHBIND_LINE'))
    assert {(p.x, p.y) for p in zone.affected_cells} <= earth.foundation_cells(engine, engine.state.actors[LEFT])


def test_response_round_budget_survives_owners_turn_start(tmp_path):
    combat, table, mid = fight(tmp_path, right_talents=[blade.FEATURE], left_score=30, right_score=2,
        cause=[{'type': 'mark', 'mark': 'Burden Mark', 'applies_to': 'target', 'duration': {'kind': 'until_removed'}}])
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Cause', target_id=LEFT)['status'] == 'COMMITTED'
    turn(table, mid, LEFT)
    send = action_sender(combat, table, mid, 'Unarmed Strike', target_id=RIGHT)
    prompt = send([])['reaction']
    assert 'Burden the Blade' in str(prompt)
    assert send([{**prompt['context'], 'selection': 'USE', 'option_ids': ['SPEND']}])['status'] == 'COMMITTED'
    spent_round = reload(combat, mid).state.round_number
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    assert engine.state.round_number == spent_round
    assert engine.state.actors[RIGHT].turn_flags['_round_earth_response'] == spent_round
    assert not earth._can_spend(engine, engine.state.actors[RIGHT])
