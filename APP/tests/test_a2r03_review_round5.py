"""A2R03R3: one generation, unused movement, and identifiable table choices."""
import pytest

from tests.test_a2r03_fix_round import _play_picked, _prepare_pressure, _add_companion, COMPANION
from tests.test_a2r03_review_repairs import _action
from tests.test_a2r11_foundations import (
    FIGHTER, SERVICE_FOE, SERVICE_ALLY, SACRED_BARE, MARROW_BARE, PULSE,
    _sacred, _marrow, _service_fight, _candidate, _play, _engine,
)


def _owner_action(bundles, name, effects):
    row = _action(bundles, name, effects, costs=[['resource:core.qi', 1]],
                  source='action:tianxia.talent.blood.' + name.replace(' ', '_'))
    foe = next(b for b in bundles if b['actor_id'] == SERVICE_FOE)
    owner = next(b for b in bundles if b['actor_id'] == FIGHTER)
    foe['action_catalog'].remove(row)
    foe['actor_template']['action_ids'].remove(row['source_definition_id'])
    # The synthetic technique must remain usable after its optional step;
    # copied Unarmed Strike reach would make the next technique disappear.
    row.update(owner_id=FIGHTER, economy='NONE', range_ft=120)
    row['parameters']['free_primary'] = True
    owner['action_catalog'].append(row)
    owner['actor_template']['action_ids'].append(row['source_definition_id'])
    return row


def _take_owner_turn(table, mid):
    for _ in range(3):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == FIGHTER:
            return
        _play(table, mid, menu['end_turn'])
    raise AssertionError('the fighter did not get a turn')


def _step(prompt):
    options = [o['id'] for o in prompt.get('choice', {}).get('options', [])]
    return next((o for o in options if o.startswith('step:')), 'DECLINE')


def test_overlapping_frame_and_won_contest_settle_method_once_at_table(tmp_path, monkeypatch):
    def prepare(bundles):
        _owner_action(bundles, 'Body contest', [{
            'type': 'contest_against', 'harmful': True, 'applies_to': 'target',
            'actor_check': {'kind': 'check', 'ability': 'STR', 'skill': 'Athletics',
                            'hazards': ['forced_movement']},
            'target_check': {'kind': 'check', 'ability': 'STR', 'skill': 'Athletics'},
            'on_success': [], 'on_fail': [],
        }])
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _sacred(), SACRED_BARE, prepare=prepare)
    _take_owner_turn(table, mid)
    def pick(prompt):
        options = [o['id'] for o in prompt.get('choice', {}).get('options', [])]
        return 'move' if 'move' in options else _step(prompt)
    _, prompts = _play_picked(table, mid, _candidate(table, mid, 'Body contest', SERVICE_FOE), pick)
    cold = _engine(combat, mid)
    contest = next(e for e in cold.events if e.event_type == 'CHECK_ROLLED'
                   and e.actor_id == FIGHTER and e.payload.get('roll_kind') == 'opposed_check')
    assert contest.payload['success'] and not contest.payload['tied']
    assert cold.state.actors[FIGHTER].resources[PULSE] == 1
    settlements = [p for p in prompts if p['reaction'] == 'Pressure Becomes Method'
                   and any(o['id'] == 'move' for o in p.get('choice', {}).get('options', []))]
    assert len(settlements) == 1
    moment = settlements[0]['moment']
    assert all(s in moment for s in ('Body contest', 'the fighter', 'the foe', 'no Action', 'Reaction', 'resource'))
    moves = [e for e in cold.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == FIGHTER]
    assert len(moves) == 1
    assert 0 < sum(e.payload.get('granted_cost_ft', 0) for e in moves) <= 10


@pytest.mark.parametrize('refusal', ['creature', 'destination', 'no_route', 'used'])
def test_state_movement_is_used_only_after_actual_movement_and_reload(tmp_path, monkeypatch, refusal):
    def prepare(bundles):
        _prepare_pressure('WIS', 30, 'frightened', held=1)(bundles)
        effects = [{'type': 'condition', 'condition': 'restrained', 'applies_to': 'self'}] if refusal == 'no_route' else []
        _owner_action(bundles, 'First pack technique', effects)
        _owner_action(bundles, 'Second pack technique', [
            {'type': 'remove_condition', 'condition': 'restrained', 'applies_to': 'self'}])
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
                                       ally=True, prepare=prepare)
    _take_owner_turn(table, mid)
    _play(table, mid, _candidate(table, mid, 'Beast-Echo Marrow State'), answer=SERVICE_ALLY)
    before = _engine(combat, mid).state.actors[FIGHTER].position
    def pick_first(prompt):
        if any(o['id'] == FIGHTER for o in prompt.get('choice', {}).get('options', [])):
            return 'DECLINE' if refusal == 'creature' else FIGHTER
        return _step(prompt) if refusal == 'used' else 'DECLINE'
    _, first_prompts = _play_picked(table, mid, _candidate(table, mid, 'First pack technique', SERVICE_FOE), pick_first)
    cold = _engine(combat, mid)
    assert bool(cold.state.actors[FIGHTER].turn_flags.get('once_per_turn:beast_echo_state_move')) is (refusal == 'used')
    assert (cold.state.actors[FIGHTER].position != before) is (refusal == 'used')
    initial = next(p for p in first_prompts if p['reaction'] == 'Beast-Echo Marrow State')
    assert all(s in initial['moment'] for s in ('First pack technique', 'the fighter', 'the ally', 'no additional Action', 'Reaction', 'resource'))
    if refusal == 'no_route':
        assert not any('choose where' in p['moment'] for p in first_prompts)
    def pick_second(prompt):
        return FIGHTER if any(o['id'] == FIGHTER for o in prompt.get('choice', {}).get('options', [])) else _step(prompt)
    _, second_prompts = _play_picked(table, mid, _candidate(table, mid, 'Second pack technique', SERVICE_FOE), pick_second)
    cold = _engine(combat, mid)
    from combat.turn_uses import current_turn_key
    assert cold.state.actors[FIGHTER].turn_flags.get('once_per_turn:beast_echo_state_move') == current_turn_key(cold)
    moves = [e for e in cold.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == FIGHTER]
    assert len(moves) == 1 and sum(e.payload.get('granted_cost_ft', 0) for e in moves) == 5
    assert bool(second_prompts) is (refusal != 'used')


@pytest.mark.parametrize('rider', ['predator', 'guard'])
def test_beast_rider_initial_prompt_names_action_creatures_and_free_cost(tmp_path, monkeypatch, rider):
    def prepare(bundles):
        if rider == 'guard':
            _prepare_pressure('WIS', 22, 'frightened', held=1)(bundles)
            _add_companion(bundles)
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
        ally=True, foe_creature_types=('Beast',), prepare=prepare,
        positions={FIGHTER: {'x': 4, 'y': 7}} if rider == 'guard' else None)
    if rider == 'predator':
        _take_owner_turn(table, mid)
        target, name, creature = SERVICE_FOE, 'Predator Answer', 'the fighter'
    else:
        target, name, creature = COMPANION, 'Marrow Pack Guard', 'bonded companion'
    _, prompts = _play(table, mid, _candidate(table, mid, 'Unarmed Strike', target), answer='move')
    prompt = next(p for p in prompts if p['reaction'] == name
                  and any(o['id'] in {'move', 'temp_hp'} for o in p.get('choice', {}).get('options', [])))
    assert all(s in prompt['moment'] for s in ('Unarmed Strike', 'the foe', creature, 'Action', 'Reaction', 'resource'))
    assert 'no ' in prompt['moment']
