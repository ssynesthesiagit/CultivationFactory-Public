"""Owned shortfall quotes survive native table choices, rollback and replay."""
from dataclasses import replace

import pytest

from combat import ext
from combat.alternative_payments import PaymentAlternative, options
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate2_runtime_models import ActionIntent
from combat.gate3_reducer import canonical_state_sha256
from combat.gate5_service import CombatService, CombatServiceError
from tests.test_auto_tabik import _engine, ME
from tests.test_lock_choices import install
from tests.test_lock2_persistence import ROOT, table_match, act

POOL = 'resource:core.stamina'
SOURCE = 'test:shortfall-technique'


def quote(engine, actor, source, costs, missing):
    if not source.startswith(SOURCE):
        return None
    # Representative owning consumer: fixed HP rate, twice-PB limit and once per turn.
    if sum(missing.values()) > 2 * actor.proficiency_bonus:
        return None
    for event in reversed(engine.events):
        if event.event_type == 'TURN_STARTED':
            break
        if event.event_type == 'ALTERNATIVE_PAYMENT_COMMITTED' and event.actor_id == actor.entity_id:
            return None
    return PaymentAlternative(source, 'Vital payment', tuple(missing.items()), hp_cost=5 * sum(missing.values()))


def priced_action(info):
    return [ActionDefinition(source_definition_id=SOURCE + ':' + info['actor_id'], display_name='Practice technique',
        owner_id=info['actor_id'], economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='SELF',
        costs=((POOL, 2),), parameters={'typed': {'source': SOURCE,
            'effects': [{'type': 'temp_hp', 'flat': 1, 'applies_to': 'self'}], 'numbers': info['numbers']}})]


def table_fixture(monkeypatch, tmp_path, current=0):
    install(monkeypatch, 'compile_actions', priced_action)
    install(monkeypatch, 'payment_shortfall', quote)
    def drain(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED':
            actor = engine.state.actors[kwargs['actor_id']]
            engine._spend_resource(actor, POOL, actor.resources[POOL] - current, 'test:drain')
    install(monkeypatch, 'event', drain)
    service, table, mid = table_match(tmp_path)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    return service, table, mid


@pytest.mark.parametrize('current', [0, 1])
def test_owned_shortfall_is_offered_asked_paid_and_replayed(monkeypatch, tmp_path, current):
    service, table, mid = table_fixture(monkeypatch, tmp_path, current)
    session = service._load_session(mid)
    actor_id = session.engine.state.current_actor_id
    before = session.engine.state.model_dump(mode='json')
    first = act(table, mid, SOURCE)
    assert first['status'] == 'REACTION_REQUIRED'
    assert 'Practice technique' in first['reaction']['moment']
    assert f'{5 * (2-current)} HP' in first['reaction']['choice']['options'][0]['label']
    assert service._load_session(mid).engine.state.model_dump(mode='json') == before
    answer = {**first['reaction']['context'], 'selection': 'USE',
              'option_ids': [first['reaction']['choice']['options'][0]['id']]}
    state = table.state(mid); menu = state['menu']
    candidate = next(g['options'][0]['candidate_id'] for g in menu['actions'] if g['source_definition_id'].startswith(SOURCE))
    assert table.act(mid, candidate, menu['decision_id'], menu['state_version'], state['last_sequence'], [answer])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[actor_id]
    assert actor.resources[POOL] == 0
    assert actor.current_hp == before['actors'][actor_id]['current_hp'] - 5 * (2-current)
    receipts = [e for e in loaded.engine.events if e.event_type == 'ALTERNATIVE_PAYMENT_COMMITTED']
    assert len(receipts) == 1 and receipts[0].payload['covered'] == {POOL: 2-current}
    assert not any(e.event_type in ('DAMAGE_COMMITTED', 'RESOURCE_GAINED') and e.source_definition_id.startswith(SOURCE) for e in loaded.engine.events)
    assert loaded.verify()['status'] == 'PASS'
    actor.action_available = True
    assert not loaded.engine._can_pay(actor, ((POOL, 2),), source_id=SOURCE + ':' + actor_id)  # owning once-per-turn rule


def test_decline_rolls_back_economy_resources_and_journal(monkeypatch, tmp_path):
    service, table, mid = table_fixture(monkeypatch, tmp_path)
    before = canonical_state_sha256(service._load_session(mid).engine.state)
    first = act(table, mid, SOURCE)
    answer = {**first['reaction']['context'], 'selection': 'DECLINE'}
    state = table.state(mid); menu = state['menu']
    cid = next(g['options'][0]['candidate_id'] for g in menu['actions'] if g['source_definition_id'].startswith(SOURCE))
    with pytest.raises(CombatServiceError, match='canceled'):
        table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], [answer])
    assert canonical_state_sha256(service._load_session(mid).engine.state) == before


@pytest.mark.parametrize('kind', ['error', 'pause'])
def test_failure_after_payment_restores_hp_resources_economy_events_and_rolls(monkeypatch, tmp_path, kind):
    service, table, mid = table_fixture(monkeypatch, tmp_path)
    first = act(table, mid, SOURCE)
    answer = {**first['reaction']['context'], 'selection': 'USE',
              'option_ids': [first['reaction']['choice']['options'][0]['id']]}
    engine = service._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id.startswith(SOURCE))
    intent = ActionIntent(intent_id='payment-failure', decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=candidate.actor_id, target_ids=candidate.target_ids,
        reaction_decisions=(answer,))
    failure = RuntimeError if kind == 'error' else ext.ControllerPause
    def fail(*args):
        raise failure('payment interruption')
    install(monkeypatch, 'payment_shortfall_paid', fail)
    before = engine.state.model_dump(mode='json'), list(engine.events), list(engine.rolls), engine.roller.counter
    with pytest.raises(failure):
        engine.execute_intent(intent)
    assert (engine.state.model_dump(mode='json'), engine.events, engine.rolls, engine.roller.counter) == before


@pytest.mark.parametrize('current', [0, 1])
def test_refund_cannot_return_resources_substituted_by_hp(monkeypatch, tmp_path, current):
    service, table, mid = table_fixture(monkeypatch, tmp_path, current)
    def discount(engine, actor, source, plan, intent):
        from combat.technique_costs import refund
        assert refund(engine, actor, source, ((POOL, 2),), POOL, 2, 'test:refund') == current
    install(monkeypatch, 'payment_shortfall_paid', discount)
    first = act(table, mid, SOURCE)
    answer = {**first['reaction']['context'], 'selection': 'USE',
              'option_ids': [first['reaction']['choice']['options'][0]['id']]}
    state = table.state(mid); menu = state['menu']
    cid = next(g['options'][0]['candidate_id'] for g in menu['actions'] if g['source_definition_id'].startswith(SOURCE))
    assert table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], [answer])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    refunded = [e for e in loaded.engine.events if e.event_type == 'RESOURCE_GAINED' and e.source_definition_id == 'test:refund']
    assert sum(e.payload['gained'] for e in refunded) == current
    assert loaded.verify()['status'] == 'PASS'


def test_quote_is_pure_owner_gated_and_honors_hp_minimum_and_cap(monkeypatch):
    install(monkeypatch, 'payment_shortfall', quote)
    engine, _ = _engine([]); actor = engine.state.actors[ME]
    actor.resource_maximums[POOL] = 30
    actor.resources[POOL] = 0
    actor.current_hp = 11
    source = SOURCE + ':owned'
    actor.passive_ids += (source,)
    before = actor.model_dump(mode='json'), list(engine.events), engine.roller.counter
    assert engine._can_pay(actor, ((POOL, 2),), source_id=source)
    assert (actor.model_dump(mode='json'), engine.events, engine.roller.counter) == before
    actor.current_hp = 10
    assert not engine._can_pay(actor, ((POOL, 2),), source_id=source)
    actor.current_hp = 11; actor.passive_ids = ()
    assert not engine._can_pay(actor, ((POOL, 2),), source_id=source)
    actor.passive_ids = (source,)
    assert not engine._can_pay(actor, ((POOL, 2*actor.proficiency_bonus+1),), source_id=source)


def test_ai_owner_pays_automatically_and_replays(monkeypatch, tmp_path):
    from combat.gate4_context import build_decision_context
    service, table, mid = table_fixture(monkeypatch, tmp_path)
    actor_id = service._load_session(mid).engine.state.current_actor_id
    service.set_controller_mode(mid, actor_id=actor_id, controller_mode='LOCAL_AUTO')
    session = service._load_session(mid)
    policy, _ = service.policies.for_actor(actor_id)
    context = build_decision_context(session.engine, policy, for_ai=True)
    # Restrict primary selection to the payment-bearing technique; the real AI
    # reaction controller still chooses and records its payment without a player.
    choices = tuple(c for c in context.legal_candidates if c.source_definition_id.startswith(SOURCE))
    assert choices
    choice = service.controller.choose_primary_action(context.model_copy(update={'legal_candidates': choices}))
    before = session.engine.state.actors[actor_id].current_hp
    session.execute_controller_choice(choice, controller=service.controller, policy_library=service.policies)
    assert session.engine.state.actors[actor_id].current_hp == before - 10
    assert CombatService(ROOT, tmp_path)._load_session(mid).verify()['status'] == 'PASS'


def test_other_resource_quote_requires_real_affordability(monkeypatch):
    engine, _ = _engine([]); actor = engine.state.actors[ME]
    actor.resource_maximums[POOL] = 5; actor.resources[POOL] = 0
    actor.passive_ids = (SOURCE,)
    alternate = 'resource:core.martial_focus'
    actor.resource_maximums[alternate] = 1; actor.resources[alternate] = 1
    plan = PaymentAlternative(SOURCE, 'Focus payment', ((POOL, 2),), costs=((alternate, 1),))
    install(monkeypatch, 'payment_shortfall', lambda *args: plan)
    assert engine._can_pay(actor, ((POOL, 2),), source_id=SOURCE)
    actor.resources[alternate] = 0
    assert not engine._can_pay(actor, ((POOL, 2),), source_id=SOURCE)


def test_shortfall_uses_final_floor_and_read_only_totals(monkeypatch):
    engine, _ = _engine([]); actor = engine.state.actors[ME]
    actor.resource_maximums[POOL] = 5; actor.resources[POOL] = 1
    actor.passive_ids = (SOURCE,); actor.current_hp = 16
    seen = []
    def offer(e, a, source, costs, missing):
        with pytest.raises(TypeError):
            costs[POOL] = 0
        with pytest.raises(TypeError):
            missing[POOL] = 0
        seen.append((dict(costs), dict(missing)))
        return quote(e, a, source, costs, missing)
    install(monkeypatch, 'payment_shortfall', offer)
    install(monkeypatch, 'technique_cost_floor', lambda *args: {POOL: 4})
    assert engine._can_pay(actor, ((POOL, 2),), source_id=SOURCE)
    assert seen == [({POOL: 4}, {POOL: 3})]
    actor.current_hp = 15
    assert not engine._can_pay(actor, ((POOL, 2),), source_id=SOURCE)


def test_fully_affordable_and_unsubscribed_paths_are_inert(monkeypatch):
    engine, _ = _engine([]); actor = engine.state.actors[ME]
    actor.resource_maximums[POOL] = 30
    actor.resources[POOL] = 10
    source = SOURCE + ':owned'
    seen = []
    install(monkeypatch, 'payment_shortfall', lambda *args: seen.append(args))
    assert engine._can_pay(actor, ((POOL, 1),), source_id=source)
    engine._spend_costs(actor, ((POOL, 1),), source)
    assert seen == []
    assert not engine._can_pay(actor, ((POOL, 10000),), source_id=source)


@pytest.mark.parametrize('change', [{'hp_cost': True}, {'hp_cost': -1}, {'minimum_hp': 0},
    {'covered': ((POOL, 1),)}, {'hp_cost': 0}, {'costs': ((POOL, 1.5),)}])
def test_invalid_quotes_cannot_unlock_actions(monkeypatch, change):
    engine, _ = _engine([]); actor = engine.state.actors[ME]
    actor.resource_maximums[POOL] = 30
    actor.resources[POOL] = 0; actor.passive_ids = (SOURCE,)
    install(monkeypatch, 'payment_shortfall', lambda *args: replace(PaymentAlternative(SOURCE, 'Vital payment', ((POOL, 2),), hp_cost=10), **change))
    with pytest.raises(ValueError):
        engine._can_pay(actor, ((POOL, 2),), source_id=SOURCE)
