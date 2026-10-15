"""Puppet Theater Domain's printed grants through table commits and fresh reloads."""
import pytest

from combat.ext import placed, vessel
from combat.typed_executor import bears_mark
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload, turn, action_sender

SPHERE = 'tianxia.sphere.puppetry'
OWNED = ['PUPPETRY_BASE_RAISE_THE_VESSEL', 'PUPPETRY_BASE_PUPPET_STRIKE']


def raise_at(combat, table, mid, x, y):
    state = table.state(mid)
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates()
        if c.display_name.startswith('Raise the Vessel (1 CP)') and c.destination.x == x and c.destination.y == y)
    menu = state['menu']
    from tests.auto28_puppetry_support import resolve
    resolve(lambda answers: table.act(mid, candidate.candidate_id, menu['decision_id'], menu['state_version'],
                     state['last_sequence'], answers), {'choice:needle.vessel_raise_move': []})
    reload(combat, mid)


def scene(tmp_path, *, domain=True, far=False, harm=False, maximum_rounds=10):
    talents = [*OWNED, *([vessel.THEATER] if domain else []), *([vessel.HARM_BODY] if harm else [])]
    combat, table, mid = fight(tmp_path, talents, spheres=[SPHERE], maximum_rounds=maximum_rounds,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 6 if far else 4, 'y': 6}},
        prepare=[{'type': 'mark', 'mark': vessel.MARK, 'applies_to': 'target',
                  'duration': {'kind': 'until_end_of_your_next_turn'}}],
        cause=[{'type': 'damage', 'flat': 100, 'damage_type': 'FORCE', 'applies_to': 'target'}] if harm else [])
    raise_at(combat, table, mid, 4, 7)
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    return combat, table, mid


@pytest.mark.parametrize('ai', [False, True])
def test_theater_grants_temp_hp_without_marking_at_cast_and_marks_at_enemy_start(tmp_path, ai):
    combat, table, mid = scene(tmp_path)
    before = reload(combat, mid)
    hp = placed.data(placed.of(before, 'vessel')[0])['hp']
    send = action_sender(combat, table, mid, vessel.THEATER, ai=ai)
    assert send([])['status'] == 'COMMITTED'
    if ai:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='MANUAL')
    engine = reload(combat, mid)
    zone = placed.of(engine, 'vessel')[0]
    assert engine.state.actors[LEFT].resources['resource:core.qi'] == before.state.actors[LEFT].resources['resource:core.qi'] - 5
    assert placed.data(zone)['temp_hp'] == 8
    assert placed.data(zone)['hp'] == hp
    active = next(c for c in engine.state.actors[LEFT].conditions.values() if c.condition_id == vessel.THEATER_ACTIVE)
    assert active.expires_on.startswith('START_OF_SLOT_AT:')
    assert all(type(v) in (int, str) for v in active.data.values())
    assert not bears_mark(engine.state.actors[RIGHT], LEFT, vessel.MARK)
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, vessel.MARK)
    assert not bears_mark(engine.state.actors[LEFT], LEFT, vessel.MARK)
    assert not any(c.condition_id.endswith('.restrained') for c in engine.state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize('domain,far', [(False, False), (True, True)])
def test_unowned_or_distant_enemy_does_not_get_a_domain_mark(tmp_path, domain, far):
    combat, table, mid = scene(tmp_path, domain=domain, far=far)
    if domain:
        assert act(table, mid, vessel.THEATER)['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    assert not bears_mark(engine.state.actors[RIGHT], LEFT, vessel.MARK)
    assert ('temp_hp' in placed.data(placed.of(engine, 'vessel')[0])) == domain


@pytest.mark.parametrize('domain,responses', [(False, 1), (True, 2)])
def test_theater_adds_exactly_one_basic_response_each_turn(tmp_path, domain, responses):
    combat, table, mid = scene(tmp_path, domain=domain)
    if domain:
        assert act(table, mid, vessel.THEATER)['status'] == 'COMMITTED'
    for _ in range(responses):
        assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
        assert act(table, mid, 'Tension Response: Cross the Limb', target_id=RIGHT)['status'] == 'COMMITTED'
        assert not bears_mark(reload(combat, mid).state.actors[RIGHT], LEFT, vessel.MARK)
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    assert not any(g['label'].startswith('Tension Response:') for g in table.state(mid)['menu']['actions'])
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    for _ in range(responses):
        assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
        assert act(table, mid, 'Tension Response: Cross the Limb', target_id=RIGHT)['status'] == 'COMMITTED'
        reload(combat, mid)


def test_domain_temp_hp_absorbs_substitute_harm_before_vessel_hp(tmp_path):
    combat, table, mid = scene(tmp_path, harm=True)
    assert act(table, mid, vessel.THEATER)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    before = placed.data(placed.of(engine, 'vessel')[0])['hp']
    turn(table, mid, RIGHT)
    send = action_sender(combat, table, mid, 'Cause', target_id=LEFT)
    result = send([])
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert 'Substitute Harm Body' in str(prompt)
    assert send([{**prompt['context'], 'selection': 'USE', 'option_ids': []}])['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    reduction = next(e.payload['reduction'] for e in engine.events
        if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == vessel.HARM_BODY)
    assert reduction > 8
    zone = placed.of(engine, 'vessel')[0]
    assert placed.data(zone)['temp_hp'] == 0
    assert placed.data(zone)['hp'] == before - (reduction - 8)


def test_theater_expires_after_ten_complete_rounds(tmp_path):
    combat, table, mid = scene(tmp_path, maximum_rounds=15)
    assert act(table, mid, vessel.THEATER)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    deadline = engine.state.round_number + 10
    active = next(c for c in engine.state.actors[LEFT].conditions.values() if c.condition_id == vessel.THEATER_ACTIVE)
    assert active.expires_on == f'START_OF_SLOT_AT:{deadline}:{engine.state.current_slot_index}'
    while combat._load_session(mid).engine.state.round_number < deadline:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert not any(c.condition_id == vessel.THEATER_ACTIVE for c in engine.state.actors[LEFT].conditions.values())
