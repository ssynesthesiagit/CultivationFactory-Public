"""Final Sol findings: pre-payment legality, shared turn clock and paid riders."""
from types import SimpleNamespace

import pytest

from combat.ext import beast_echo_marrow as marrow, foundation_sacred_body as body
from combat.gate2_rolls import DeterministicRollAuthority
from tests.test_a2r03_fix_round import _prepare_pressure, _play_picked
from tests.test_a2r03_review_repairs import _action
from tests.test_a2r03_review_round5 import _owner_action, _take_owner_turn, _step
from tests.test_a2r11_foundations import (
    FIGHTER, SERVICE_FOE, SERVICE_ALLY, SACRED_BARE, MARROW_BARE, PULSE,
    _sacred, _marrow, _service_fight, _candidate, _play, _engine, _act,
)


@pytest.mark.parametrize('partner_x', [None, 16, 15])
def test_state_partner_required_before_payment_at_table(tmp_path, monkeypatch, partner_x):
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
        ally=partner_x is not None, prepare=_prepare_pressure('WIS', 30, 'frightened', held=1),
        positions={SERVICE_ALLY: {'x': partner_x, 'y': 6}} if partner_x else None)
    _take_owner_turn(table, mid)
    before = _engine(combat, mid).state.actors[FIGHTER]
    if partner_x is not None:
        engine = _engine(combat, mid)
        partner = engine.state.actors[SERVICE_ALLY]
        action = next(a for a in engine.action_catalog.values() if a.source_definition_id == marrow.STATE_ACTION)
        owner = engine.state.actors[FIGHTER]
        # Exercise the same predicate as a partner crosses the exact boundary.
        for x, permitted in [(15, True), (16, False), (15, True)]:
            partner.position = partner.position.model_copy(update={'x': x})
            assert (marrow.state_once_per_fight(engine, owner, None, action) is not False) is permitted
    available = any('Beast-Echo Marrow State' in g['label'] for g in table.state(mid)['menu']['actions'])
    assert available is (partner_x == 15)  # 60 ft inclusive; x=16 is 65 ft
    if available:
        _play(table, mid, _candidate(table, mid, 'Beast-Echo Marrow State'), answer=SERVICE_ALLY)
        assert any(c.condition_id == marrow.STATE_CONDITION for c in
                   _engine(combat, mid).state.actors[SERVICE_ALLY].conditions.values())
    else:
        # Stale/forged requests cannot pay for an action absent from the menu.
        try:
            _act(table, mid, 'action:' + marrow.STATE_ACTION)
        except Exception as exc:
            assert 'candidate' in str(exc).lower() or 'legal' in str(exc).lower()
        after = _engine(combat, mid).state.actors[FIGHTER]
        assert after.resources == before.resources
        assert (after.action_available, after.bonus_action_available, after.reaction_available) == (
            before.action_available, before.bonus_action_available, before.reaction_available)


def test_state_pair_shares_actual_turn_allowance_after_table_reload(tmp_path, monkeypatch):
    def prepare(bundles):
        _prepare_pressure('WIS', 30, 'frightened', held=1)(bundles)
        _owner_action(bundles, 'Pack technique', [])
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
                                       ally=True, prepare=prepare)
    _take_owner_turn(table, mid)
    _play(table, mid, _candidate(table, mid, 'Beast-Echo Marrow State'), answer=SERVICE_ALLY)
    def pick(prompt):
        return FIGHTER if any(o['id'] == FIGHTER for o in prompt.get('choice', {}).get('options', [])) else _step(prompt)
    _play_picked(table, mid, _candidate(table, mid, 'Pack technique', SERVICE_FOE), pick)
    cold = _engine(combat, mid)
    action = next(a for a in cold.action_catalog.values() if a.display_name == 'Pack technique')
    def trigger(engine, who):
        marrow.state_technique_move(SimpleNamespace(engine=engine, actor=engine.state.actors[who],
            action=action, typed=action.parameters['typed']))
    # A second member's compatible off-turn technique shares the spent budget.
    def forbidden(*args, **kwargs):
        raise AssertionError('pair already moved this turn')
    with monkeypatch.context() as patch:
        patch.setattr(marrow.needle, 'ask', forbidden)
        trigger(cold, SERVICE_ALLY)
    _play(table, mid, table.state(mid)['menu']['end_turn'])
    cold = _engine(combat, mid)
    assert cold.state.current_actor_id != FIGHTER
    # On this later creature turn, the original owner's compatible reaction
    # technique may offer movement again, even before their own next turn.
    calls = []
    monkeypatch.setattr(marrow.needle, 'ask', lambda *a, **kw: calls.append(kw) or [FIGHTER])
    from combat.ext import granted_moves
    monkeypatch.setattr(granted_moves, 'choose', lambda *a, **kw: 5)
    trigger(cold, FIGHTER)
    assert len(calls) == 1
    trigger(cold, SERVICE_ALLY)
    assert len(calls) == 1


@pytest.mark.parametrize('outcome', ['win', 'loss', 'tie'])
def test_defending_physical_contest_generates_only_for_winner_at_table(tmp_path, monkeypatch, outcome):
    def prepare(bundles):
        _action(bundles, 'Physical contest', [{'type': 'contest_against', 'harmful': True,
            'applies_to': 'target',
            'actor_check': {'kind': 'check', 'ability': 'STR'},
            'target_check': {'kind': 'check', 'ability': 'CON'},
            'on_success': [], 'on_fail': []}])
        # No Frame hazards, and equal modifiers make the tie explicit.
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _sacred(), SACRED_BARE, prepare=prepare)
    # Every preview/replay starts a fresh deterministic roller. Target first.
    def die(roller, sides):
        counter = roller.counter
        roller.counter += 1
        if sides != 20:
            return 2, counter
        index = getattr(roller, '_round6_die', 0)
        roller._round6_die = index + 1
        return {'win': [18, 2], 'loss': [2, 18], 'tie': [10, 10]}[outcome][index % 2], counter
    monkeypatch.setattr(DeterministicRollAuthority, '_die', die)
    _, prompts = _play(table, mid, _candidate(table, mid, 'Physical contest', FIGHTER))
    cold = _engine(combat, mid)
    contest = next(e for e in reversed(cold.events) if e.event_type == 'CHECK_ROLLED'
                   and e.payload.get('roll_kind') == 'opposed_check')
    assert bool(contest.payload['tied']) is (outcome == 'tie')
    assert bool(contest.payload['success']) is (outcome == 'loss')
    assert cold.state.actors[FIGHTER].resources[PULSE] == (1 if outcome == 'win' else 0)
    settlements = [p for p in prompts if p['reaction'] == 'Pressure Becomes Method']
    assert len(settlements) == (1 if outcome == 'win' else 0)


@pytest.mark.parametrize('consent', ['USE', 'DECLINE'])
def test_guard_quote_is_pure_and_blood_requires_paid_settlement(tmp_path, monkeypatch, consent):
    def prepare(bundles):
        _prepare_pressure('CON', 30, 'poisoned', held=1)(bundles)
        _action(bundles, 'Corruptive hit', [{'type': 'damage', 'applies_to': 'target',
            'flat': 30, 'damage_types': ['necrotic']}])
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _sacred(), SACRED_BARE, prepare=prepare)
    engine = _engine(combat, mid)
    owner, foe = engine.state.actors[FIGHTER], engine.state.actors[SERVICE_FOE]
    engine._typed_pending_damage_type = 'necrotic'
    before = dict(owner.conditions)
    for _ in range(2):
        assert body.guard_corruptive_bonus(engine, owner, owner, foe, {'feature_id': body.GUARD}) == 4
    assert owner.conditions == before
    _play(table, mid, _candidate(table, mid, 'Corruptive hit', FIGHTER), answer=consent)
    cold = _engine(combat, mid)
    marks = [c for c in cold.state.actors[FIGHTER].conditions.values() if c.condition_id == body.GUARD_ADVANTAGE]
    assert bool(marks) is (consent == 'USE')
    if marks:
        assert marks[0].data['source'] == SERVICE_FOE
