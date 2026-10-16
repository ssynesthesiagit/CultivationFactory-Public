"""The explanatory query observes exactly the candidate checks and stays pure."""
import copy
import pytest
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from tests.h1_support import duel, ME, FOE, ROOT
from tests.test_lock_choices import install

SOURCE = 'test:availability'
QI = 'resource:core.qi'


def fixture(*, parameters=None, costs=(), target='SELF', economy=EconomyKind.ACTION):
    engine = duel([])
    action = ActionDefinition(source_definition_id=SOURCE, display_name='Test action', owner_id=ME,
        economy=economy, resolution_kind='TYPED', target_kind=target, range_ft=5,
        costs=costs, parameters=parameters or {})
    engine.action_catalog[SOURCE] = action
    engine.state.actors[ME].action_ids += (SOURCE,)
    return engine, engine.state.actors[ME]


def ask(engine):
    before = copy.deepcopy(engine.__dict__)
    result = engine.action_availability(ME, SOURCE)
    assert engine.state.model_dump(mode='json') == before['state'].model_dump(mode='json')
    assert engine.events == before['events'] and engine.rolls == before['rolls']
    assert engine.roller.counter == before['roller'].counter
    assert set(engine.__dict__) == set(before)
    # Existing cache contents stay unchanged, not merely the serialized state.
    for key in before:
        if 'cache' in key or key == '_augment_families':
            assert engine.__dict__[key] == before[key]
    candidates = engine.legal_candidates()
    assert result['available'] == any(c.source_definition_id == SOURCE and c.actor_id == ME for c in candidates)
    return result


@pytest.mark.parametrize('parameters,code', [
    ({'requires_condition': 'condition:test.missing'}, 'REQUIRES_CONDITION'),
    ({'requires_turn_flag': 'missing'}, 'REQUIRES_TURN_FLAG'),
    ({'requires_turn_flags': ['one', 'two']}, 'REQUIRES_TURN_FLAGS'),
    ({'requires_disabled_action': 'missing'}, 'DROPPED_WEAPON'),
    ({'requires_dropped_nearby': True}, 'NO_DROPPED_WEAPON'),
    ({'requires_held_weapon': 'missing'}, 'HELD_WEAPON'),
    ({'requires_resource': {QI: 100}}, 'RESOURCE_PREREQUISITE'),
    ({'requires_grappling': True}, 'GRAPPLE'),
    ({'summon_command': 'missing'}, 'SUMMON_COMMAND'),
    ({'hp_band': 'below_half'}, 'HP_BAND'),
])
def test_native_prerequisites_share_the_actual_refusal(parameters, code):
    engine, actor = fixture(parameters=parameters)
    assert ask(engine)['code'] == code


@pytest.mark.parametrize('economy,flag,code', [
    (EconomyKind.ACTION, 'action_available', 'ACTION'),
    (EconomyKind.BONUS_ACTION, 'bonus_action_available', 'BONUS_ACTION')])
def test_economy_precedes_resource_refusal(economy, flag, code):
    engine, actor = fixture(costs=((QI, 99),), economy=economy)
    setattr(actor, flag, False)
    assert ask(engine)['code'] == code


def test_costs_use_the_real_floor_and_aggregate_duplicate_pools(monkeypatch):
    engine, actor = fixture(costs=((QI, 2), (QI, 3)))
    actor.resources[QI] = 5
    assert ask(engine)['available']
    install(monkeypatch, 'technique_cost_floor', lambda e, a, s, *args: {QI: 7} if s == SOURCE else None)
    result = ask(engine)
    assert result['code'] == 'COST' and '7 Qi (you have 5)' in result['reason']
    assert result['details']['costs'] == [[QI, 7]]


def test_owned_alternative_payment_keeps_action_available(monkeypatch):
    from combat.alternative_payments import PaymentAlternative
    engine, actor = fixture(costs=((QI, 5),))
    actor.resources[QI] = 0
    actor.passive_ids += ('test:substitution',)
    install(monkeypatch, 'payment_shortfall', lambda e, a, s, *args:
            PaymentAlternative('test:substitution', 'Pay with HP', ((QI, 5),), hp_cost=5) if s == SOURCE else None)
    assert ask(engine)['available']
    assert actor.current_hp == actor.maximum_hp


def test_unavailable_target_and_custom_permission_reasons(monkeypatch):
    engine, actor = fixture(target='HOSTILE_ENTITY')
    assert ask(engine)['available']
    install(monkeypatch, 'recipient_allowed', lambda *args: False)
    install(monkeypatch, 'recipient_unavailability', lambda *args: 'The target has already received this benefit this fight.')
    assert ask(engine)['reason'] == 'The target has already received this benefit this fight.'
    install(monkeypatch, 'recipient_allowed', lambda *args: True)
    install(monkeypatch, 'candidate_allowed', lambda e, a, c, action: False if c.source_definition_id == SOURCE else None)
    install(monkeypatch, 'candidate_unavailability', lambda *args: 'Choose a different attack after using this stance.')
    assert ask(engine)['reason'] == 'Choose a different attack after using this stance.'


@pytest.mark.parametrize('case,code', [('inactive', 'INACTIVE'), ('turn', 'TURN'),
    ('no_actions', 'NO_ACTIONS'), ('setup', 'SETUP'), ('uses', 'USE_LIMIT'),
    ('range', 'TARGET_RANGE'), ('pattern', 'NO_PATTERN'), ('area', 'NO_AREA')])
def test_context_limits_and_target_domains(case, code):
    from combat.gate2_runtime_models import FightSetupTask, Position
    target = {'range': 'HOSTILE_ENTITY', 'pattern': 'VISIBLE_ACTIVE_PATTERN', 'area': 'CELL'}.get(case, 'SELF')
    engine, actor = fixture(target=target)
    if case == 'inactive': actor.active = False
    if case == 'turn': engine.state.current_actor_id = FOE
    if case == 'setup': engine.state.setup_tasks = (FightSetupTask(actor_id=ME, source_id=SOURCE),)
    if case == 'no_actions':
        engine._apply_condition(actor, 'condition:typed.incapacitated', 'test:stun', FOE, expires_on='UNTIL_REMOVED')
    if case == 'uses':
        pool = 'resource:uses.' + SOURCE
        actor.resources[pool] = 0
        engine.action_catalog[SOURCE] = engine.action_catalog[SOURCE].model_copy(update={'costs': ((pool, 1),)})
    if case in ('range', 'area'):
        engine.state.actors[FOE].position = Position(x=10, y=10)
    assert ask(engine)['code'] == code


def test_hidden_loadout_reason_and_candidate_identity():
    from combat.loadout import AUGMENTS
    engine, actor = fixture(parameters={'augment_loadout': {
        'combos': {'wide': 'test:wide'}, 'augments': [{'key': 'wide', 'name': 'Wider area'}]}})
    engine._apply_condition(actor, AUGMENTS, SOURCE, ME, expires_on='UNTIL_REMOVED',
                            data={'family': SOURCE, 'augments': ['wide']})
    assert ask(engine)['code'] == 'LOADOUT'


def test_no_target_explanation_exposes_hidden_identity(monkeypatch):
    engine, actor = fixture(target='HOSTILE_ENTITY')
    enemy = engine.state.actors[FOE]
    enemy.display_name = 'Secret creature name'
    install(monkeypatch, 'target_eligibility', lambda *args: False)
    result = ask(engine)
    assert enemy.display_name not in result['reason'] and enemy.entity_id not in result['reason']


@pytest.mark.parametrize('case,code', [('pending', 'PENDING'), ('finished', 'FINISHED'),
    ('absent', 'BLOCKING_CONDITION'), ('turn_limit', 'TURN_LIMIT'), ('disabled', 'WEAPON_DISABLED'),
    ('shape', 'COST'), ('summon_present', 'SUMMON_PRESENT')])
def test_other_authoritative_rejections(case, code):
    from combat.gate2_runtime_models import PendingResolution, TerminalResult
    params = {'absent': {'requires_absent_condition': 'condition:test.active'},
              'turn_limit': {'blocked_by_turn_flag': 'used'}, 'shape': {'shape_costs': {QI: 99}},
              'summon_present': {'summon_group': 'test:group'}}.get(case, {})
    engine, actor = fixture(parameters=params)
    if case == 'pending':
        engine.state.pending_resolution = PendingResolution(transaction_id='test:pending', source_definition_id=SOURCE,
            intent_id='test:intent', actor_id=ME, target_ids=(), stage='FOLLOW_UP')
    if case == 'finished':
        engine.state.terminal_result = TerminalResult(kind='VICTORY', reason='test', event_sequence=engine.state.event_sequence)
    if case == 'absent':
        engine._apply_condition(actor, 'condition:test.active', SOURCE, ME, expires_on='UNTIL_REMOVED')
    if case == 'turn_limit': actor.turn_flags['used'] = True
    if case == 'disabled':
        engine._apply_condition(actor, 'condition:test.disarmed', SOURCE, ME, expires_on='UNTIL_REMOVED',
                                data={'disables_action': SOURCE})
    if case == 'summon_present':
        engine.state.actors[FOE].summon = {'owner': ME, 'group': 'test:group', 'status': 'present'}
    assert ask(engine)['code'] == code


def test_real_table_query_does_not_change_commits_or_saved_state(tmp_path):
    from combat.gate5_service import CombatService
    from tests.test_tabletop_hunt6 import table_fight, LEFT, HOLD
    from tests.test_lock2_persistence import act
    svc, table, mid = table_fight(tmp_path, [])
    engine = svc._load_session(mid).engine
    state = copy.deepcopy(engine.state.model_dump(mode='json'))
    events = list(engine.events)
    choices = tuple(c.model_dump(mode='json') for c in engine.legal_candidates())
    for source in engine.state.actors[LEFT].action_ids:
        answer = engine.action_availability(LEFT, source)
        assert answer['available'] == any(c['source_definition_id'] == source for c in choices)
    assert engine.state.model_dump(mode='json') == state and engine.events == events
    assert tuple(c.model_dump(mode='json') for c in engine.legal_candidates()) == choices
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    assert CombatService(ROOT, tmp_path)._load_session(mid).verify()['status'] == 'PASS'
