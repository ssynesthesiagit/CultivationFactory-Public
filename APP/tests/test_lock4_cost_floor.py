"""Cost floors apply before affordability/payment, including plug-in discounts."""
import pytest

from combat import ext
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate5_service import CombatService
from combat.technique_costs import permitted_refund
from tests.test_auto_tabik import _engine, ME
from tests.test_lock_choices import install
from tests.test_lock2_persistence import ROOT, table_match, act

POOL = 'resource:core.stamina'
SOURCE = 'test:priced-technique'


def test_floor_combines_by_max_after_discount_and_keeps_printed_costs(monkeypatch):
    engine, _ = _engine([])
    actor = engine.state.actors[ME]
    listed, discounted = ((POOL, 5),), ((POOL, 2),)
    before = actor.model_dump(mode='json'), list(engine.events), engine.roller.counter
    seen = []
    def floor(e, a, source, printed, current):
        seen.append((dict(printed), dict(current)))
        with pytest.raises(TypeError):
            printed[POOL] = 100
        return dict(printed)
    install(monkeypatch, 'technique_cost_floor', floor)
    ext._HOOKS['technique_cost_floor'].append(lambda *args: {POOL: 3})
    assert engine.effective_costs(actor, SOURCE, listed, reduced_costs=discounted) == listed
    assert seen == [({POOL: 5}, {POOL: 2})]
    assert (actor.model_dump(mode='json'), engine.events, engine.roller.counter) == before
    assert engine.effective_costs(actor, SOURCE, listed, reduced_costs=((POOL, 7),)) == ((POOL, 7),)
    assert permitted_refund(engine, actor, SOURCE, listed, POOL, 3) == 0


@pytest.mark.parametrize('answer', [None, {}, {POOL: 1}])
def test_no_floor_preserves_proposed_rows_exactly(monkeypatch, answer):
    install(monkeypatch, 'technique_cost_floor', lambda *args: answer)
    engine, _ = _engine([])
    rows = ((POOL, 0), (POOL, 2))
    assert engine.effective_costs(engine.state.actors[ME], SOURCE, ((POOL, 5),), reduced_costs=rows) == rows


@pytest.mark.parametrize('answer', [True, 3, {POOL: True}, {POOL: -1}, {POOL: 1.5}, {'resource:unlisted': 2}])
def test_invalid_floors_reject_without_spending(monkeypatch, answer):
    install(monkeypatch, 'technique_cost_floor', lambda *args: answer)
    engine, _ = _engine([])
    actor = engine.state.actors[ME]
    before = actor.model_dump(mode='json'), list(engine.events)
    with pytest.raises(ValueError, match='technique_cost_floor'):
        engine._spend_costs(actor, ((POOL, 2),), SOURCE)
    assert (actor.model_dump(mode='json'), engine.events) == before


def priced_action(info):
    return [ActionDefinition(source_definition_id=SOURCE + ':' + info['actor_id'], display_name='Practice technique (2 Stamina)',
        owner_id=info['actor_id'], economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='SELF',
        costs=((POOL, 2),), parameters={'typed': {'source': SOURCE, 'effects': [], 'numbers': info['numbers']}})]


def test_native_affordability_and_payment_use_same_floor_and_replay(monkeypatch, tmp_path):
    install(monkeypatch, 'compile_actions', priced_action)
    install(monkeypatch, 'technique_cost_floor', lambda e, a, source, listed, current: {POOL: 4} if source.startswith(SOURCE) else None)
    service, table, mid = table_match(tmp_path)
    actor_id = table.state(mid)['menu']['actor_id']
    loaded = service._load_session(mid)
    actor = loaded.engine.state.actors[actor_id]
    start = actor.resources[POOL]
    action = loaded.engine.action_catalog[SOURCE + ':' + actor_id]
    actor.resources[POOL] = 3
    assert not loaded.engine._action_candidates(actor, action)
    actor.resources[POOL] = 4
    assert loaded.engine._action_candidates(actor, action)
    assert act(table, mid, SOURCE)['status'] == 'COMMITTED'
    reopened = CombatService(ROOT, tmp_path)._load_session(mid)
    assert reopened.engine.state.actors[actor_id].resources[POOL] == start - 4
    assert reopened.engine.action_catalog[action.source_definition_id].costs == ((POOL, 2),)
    assert reopened.verify()['status'] == reopened.mechanical.replay()['status'] == 'PASS'


def test_blossom_affordability_and_discount_query_respect_floor(monkeypatch):
    from combat.ext import blossom
    engine, _ = _engine([])
    actor = engine.state.actors[ME]
    engine._apply_condition(actor, blossom.SCRIPTURE_ON, 'test:scripture', ME, expires_on='UNTIL_REMOVED')
    kit = {'pool': POOL, 'source': 'test:blossom', 'owned': set()}
    assert blossom._cost(engine, actor, kit, 'seed', False) == 2
    actor.resources[POOL] = 2
    assert blossom._blocker(engine, actor, kit, 'seed', None) is None
    install(monkeypatch, 'technique_cost_floor', lambda e, a, source, printed, current: dict(printed))
    assert blossom._cost(engine, actor, kit, 'seed', False) == 3
    assert blossom._blocker(engine, actor, kit, 'seed', None) is not None


@pytest.mark.parametrize('feature', [
    'tianxia.path.qi_cultivation.feature.golden_core_efficiency',
    'tianxia.subpath.qi.devil_heart_second_furnace.feature.demon_seed_overdraw'])
def test_existing_qi_discount_cannot_refund_past_printed_floor(monkeypatch, feature):
    from combat.ext import qi_path, devil_heart_second_furnace
    from combat.typed_executor import Context
    from tests.test_auto_subpaths import _sheet, _fight, ME as OWNER
    engine = _fight(_sheet([feature]))
    actor = engine.state.actors[OWNER]
    action = ActionDefinition(source_definition_id=SOURCE, display_name='Practice technique (2 Qi)',
        owner_id=OWNER, economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='SELF',
        costs=(('resource:core.qi', 2),))
    ctx = Context(engine, actor, action, None, {'numbers': {'pb': 4}}, [actor], actor)
    engine._spend_costs(actor, action.costs, SOURCE)
    after_payment = actor.resources['resource:core.qi']
    install(monkeypatch, 'technique_cost_floor', lambda e, a, source, printed, current: dict(printed))
    callback = qi_path.golden_core_efficiency if feature.endswith('golden_core_efficiency') else devil_heart_second_furnace.demon_seed_overdraw
    callback(ctx)
    assert actor.resources['resource:core.qi'] == after_payment
    assert not any(e.event_type == 'RESOURCE_GAINED' and e.payload.get('resource_id') == 'resource:core.qi' for e in engine.events)


def test_multiple_refunds_cannot_collectively_cross_partial_floor(monkeypatch):
    from combat.technique_costs import refund
    engine, _ = _engine([])
    actor = engine.state.actors[ME]
    actor.resources[POOL] = actor.resource_maximums[POOL] = 10
    listed = ((POOL, 5),)
    engine._spend_costs(actor, listed, SOURCE)
    after_payment = actor.resources[POOL]
    install(monkeypatch, 'technique_cost_floor', lambda *args: {POOL: 2})
    assert refund(engine, actor, SOURCE, listed, POOL, 1, 'test:first-discount') == 1
    assert refund(engine, actor, SOURCE, listed, POOL, 4, 'test:second-discount') == 2
    assert refund(engine, actor, SOURCE, listed, POOL, 1, 'test:third-discount') == 0
    assert actor.resources[POOL] == after_payment + 3


def test_refund_receipt_survives_table_reload_and_replay(monkeypatch, tmp_path):
    from combat.technique_costs import refund
    install(monkeypatch, 'compile_actions', priced_action)
    install(monkeypatch, 'technique_cost_floor', lambda e, a, source, printed, current: {POOL: 1} if source.startswith(SOURCE) else None)
    def discount(ctx):
        if ctx.source.startswith(SOURCE):
            refund(ctx.engine, ctx.actor, ctx.source, ctx.action.costs, POOL, 2, 'test:discount')
    install(monkeypatch, 'technique_used', discount)
    service, table, mid = table_match(tmp_path)
    actor_id = table.state(mid)['menu']['actor_id']
    start = service._load_session(mid).engine.state.actors[actor_id].resources[POOL]
    assert act(table, mid, SOURCE)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[actor_id].resources[POOL] == start - 1
    gain = next(e for e in loaded.engine.events if e.event_type == 'RESOURCE_GAINED')
    assert gain.payload['cost_source_id'] == SOURCE + ':' + actor_id
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
