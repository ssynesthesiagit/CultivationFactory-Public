"""Hunt 170/171: Speed expiry and bounded Hold through table commits/cold loads."""
import pytest

from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext.forged_exhaustion import level
from tests.auto8f1_table_support import OWNER, FOE, fixture, candidate_id
from tests.test_lock_choices import install

BOOST = 'TAL_ATHLETICS_SPEED_BOOST'
HOLD = 'system:combat.hold_position'


def actions(bundles):
    for bundle in bundles:
        if bundle['actor_id'] != OWNER:
            continue
        for name, effects in (
            ('End Speed Boost', [{'type': 'remove_condition', 'condition': 'speed_boost', 'applies_to': 'self'}]),
            ('Gain Exhaustion', [{'type': 'exhaustion', 'amount': 1, 'applies_to': 'self'}]),
            ('Recover Exhaustion', [{'type': 'exhaustion', 'amount': -1, 'applies_to': 'self'}]),
            ('Gain Speed', [{'type': 'condition', 'condition': 'hunt170_speed', 'applies_to': 'self'}]),
            ('End Speed', [{'type': 'remove_condition', 'condition': 'hunt170_speed', 'applies_to': 'self'}]),
        ):
            action = ActionDefinition(source_definition_id='action:test.hunt170.' + name.lower().replace(' ', '_'),
                display_name=name, owner_id=OWNER, economy=EconomyKind.NONE,
                resolution_kind='TYPED', target_kind='SELF', parameters={'free_primary': True, 'typed': {
                    'effects': effects, 'numbers': {}, 'riders': [], 'duration': {'kind': 'instant'}}})
            bundle['action_catalog'].append(action.model_dump(mode='json'))
            bundle['actor_template']['action_ids'].append(action.source_definition_id)


def game(tmp_path, talents=()):
    return fixture(tmp_path, list(talents), seed='HUNT170-' + tmp_path.name,
                   ask=False, bundle_transform=actions)


def use(g, name):
    return g['commit'](candidate_id(g['menu'](), name))


def cold(g):
    service = CombatService(g['combat'].source_root, g['userdata'])
    session = service._load_session(g['match_id'])
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine, TabletopService(service, g['userdata'])


def receipts(engine, after=0):
    return [e for e in engine.events if e.sequence > after and e.actor_id == OWNER
            and e.event_type == 'MOVEMENT_GRANTED' and e.payload.get('reason') == 'speed']


@pytest.mark.parametrize('deadline', [False, True])
def test_speed_boost_removal_deducts_fifty_and_expiry_journals_exhaustion(tmp_path, deadline):
    g = game(tmp_path, [BOOST])
    use(g, 'Speed Boost: +50 feet of Speed')
    actor = g['reload_owner']()
    boost = next(c for c in actor.conditions.values() if c.condition_id == 'condition:typed.speed_boost')
    last_turn = int(boost.expires_on.rsplit(':', 1)[-1])
    # A new turn includes the boosted initial allowance, exactly as in H170.
    while g['reload_owner']().turns_started < (last_turn if deadline else 2):
        g['commit'](g['menu']()['end_turn'])
        g['to_owner']()
    before = g['reload_owner']().movement_remaining_ft
    assert before == 80
    sequence = g['stored_engine']().state.event_sequence
    if deadline:
        g['commit'](g['menu']()['end_turn'])
    else:
        use(g, 'End Speed Boost')
    engine, table = cold(g)
    owner = engine.state.actors[OWNER]
    assert owner.movement_remaining_ft == before - 50 - (5 if deadline else 0)
    assert level(owner) == (1 if deadline else 0)
    assert sum(e.payload['distance_ft'] for e in receipts(engine, sequence)) == (-55 if deadline else -50)
    feed = table.events(g['match_id'], sequence)['events']
    visible = {e['sequence']: e for e in feed}
    for receipt in receipts(engine, sequence):
        assert receipt.sequence in visible
        assert str(receipt.payload['remaining_ft']) in visible[receipt.sequence]['summary']


def test_exhaustion_gain_and_recovery_journal_composed_speed_deltas(tmp_path):
    g = game(tmp_path)
    before = g['reload_owner']().movement_remaining_ft
    use(g, 'Gain Exhaustion')
    engine, _ = cold(g)
    assert engine.state.actors[OWNER].movement_remaining_ft == before - 5
    assert receipts(engine)[-1].payload['distance_ft'] == -5
    use(g, 'Recover Exhaustion')
    engine, _ = cold(g)
    assert engine.state.actors[OWNER].movement_remaining_ft == before
    assert receipts(engine)[-1].payload['distance_ft'] == 5


def test_generic_speed_bonus_removal_preserves_spend_and_clamps(tmp_path, monkeypatch):
    def condition_state(ctx, subject, effect):
        if effect.get('condition') == 'hunt170_speed':
            return {'data': {'speed_delta': 20}, 'expires_on': 'UNTIL_REMOVED'}
    install(monkeypatch, 'condition_state', condition_state)
    g = game(tmp_path, [BOOST])
    use(g, 'Gain Speed')
    g['commit'](g['menu']()['end_turn'])
    g['to_owner']()
    before = g['reload_owner']().movement_remaining_ft
    assert before == 50
    use(g, 'End Speed')
    engine, _ = cold(g)
    assert engine.state.actors[OWNER].movement_remaining_ft == before - 20
    assert receipts(engine)[-1].payload['distance_ft'] == -20
    # Spend most of the boosted pool before removal: the lost Speed cannot
    # drive unspent movement negative or refund the movement already spent.
    use(g, 'Speed Boost: +50 feet of Speed')
    g['commit'](g['menu']()['end_turn'])
    g['to_owner']()
    menu = g['menu']()
    moves = [m for m in menu['moves'] if 30 < m['cost_ft'] < 80]
    assert moves
    g['commit'](max(moves, key=lambda m: m['cost_ft'])['candidate_id'])
    before = g['reload_owner']().movement_remaining_ft
    use(g, 'End Speed Boost')
    engine, _ = cold(g)
    assert engine.state.actors[OWNER].movement_remaining_ft == max(0, before - 50)
    assert receipts(engine)[-1].payload['distance_ft'] == -min(before, 50)


def test_speed_bonus_expires_between_holder_turns_and_reloads(tmp_path, monkeypatch):
    from combat.ext.effect_durations import token
    def condition_state(ctx, subject, effect):
        if effect.get('condition') == 'hunt170_speed':
            return {'data': {'speed_delta': 20}, 'expires_on': token(
                'start', FOE, ctx.engine.state.actors[FOE].turns_started + 2)}
    install(monkeypatch, 'condition_state', condition_state)
    g = game(tmp_path)
    use(g, 'Gain Speed')
    g['commit'](g['menu']()['end_turn'])
    g['to_owner']()
    assert g['reload_owner']().movement_remaining_ft == 50
    g['commit'](g['menu']()['end_turn'])
    g['turn_of'](FOE)
    engine, _ = cold(g)
    assert engine.state.current_actor_id == FOE
    assert engine.state.actors[OWNER].movement_remaining_ft == 30
    assert receipts(engine)[-1].payload['distance_ft'] == -20


def test_hold_once_per_turn_reloads_resets_and_ai_does_not_repeat(tmp_path):
    g = fixture(tmp_path, [], seed='HUNT171-HOLD', ask=False)
    description = next(a['description'] for a in g['menu']()['actions'] if a['source_definition_id'] == HOLD)
    assert 'once on your turn' in description and 'without spending an Action' in description
    use(g, 'Hold position')
    engine, table = cold(g)
    owner = engine.state.actors[OWNER]
    assert owner.turn_flags['once_per_turn:' + HOLD] == owner.turns_started
    assert sum(e.event_type == 'ONCE_PER_TURN_CLAIMED' and e.source_definition_id == HOLD for e in engine.events) == 1
    assert not any(c.source_definition_id == HOLD for c in engine.legal_candidates())
    state = table.state(g['match_id'])
    assert not any(a['source_definition_id'] == HOLD for a in state['menu']['actions'])
    g['combat'].set_controller_mode(g['match_id'], actor_id=OWNER, controller_mode='LOCAL_AUTO')
    for _ in range(8):
        state = table.state(g['match_id'])
        if state['menu']['actor_id'] != OWNER:
            break
        result = table.auto_step(g['match_id'], state['last_sequence'])
        assert result['status'] == 'COMMITTED', result
        engine, table = cold(g)
    assert engine.state.current_actor_id != OWNER
    assert sum(e.event_type == 'HOLD_POSITION_COMMITTED' and e.actor_id == OWNER for e in engine.events) == 1
    g['combat'].set_controller_mode(g['match_id'], actor_id=OWNER, controller_mode='MANUAL')
    g['to_owner']()
    engine, _ = cold(g)
    assert any(c.source_definition_id == HOLD for c in engine.legal_candidates())
    use(g, 'Hold position')
    engine, _ = cold(g)
    assert sum(e.event_type == 'HOLD_POSITION_COMMITTED' and e.actor_id == OWNER for e in engine.events) == 2
