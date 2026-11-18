"""Native policy regression with a test-only protected route and entry attack."""
import pytest

from combat import ext
from combat.gate2_engine import SYSTEM_OPPORTUNITY
from combat.gate2_runtime_content import AN, LEE
from combat.gate2_runtime_models import ActionDefinition, Position, ReactionDecision, DiceSpec
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat import movement_steps
from tests.test_auto_docket import ROOT, ME, _sheet
from tests.test_lock_choices import install
from tests.test_lock26_movement_concentration_seams import _execute


SOURCE = 'action:test.lock27.route'


def _setup(tmp_path, monkeypatch, outcome=None):
    install(monkeypatch, 'compile_actions', lambda info: [ActionDefinition(
        source_definition_id=SOURCE, display_name='Protected route', owner_id=info['actor_id'],
        economy='NONE', resolution_kind='TYPED', target_kind='SELF',
        parameters={'typed': {'source': SOURCE, 'numbers': info['numbers'],
                              'effects': [{'type': 'test_lock27_route'}]}})])

    def route(ctx, row):
        ctx.engine.grant_movement(ctx.actor, tuple(Position(x=x, y=6) for x in (5, 4, 3)),
            SOURCE, feet=10, intent=ctx.intent, ignore_oa_from=(LEE,))

    monkeypatch.setitem(ext.effects(), 'test_lock27_route', route)
    seen = []
    paused = []

    def nested(engine, attacker, target, request, context):
        if attacker.entity_id != AN or target.entity_id != ME:
            return None
        previous = attacker.position
        engine.grant_movement(attacker, (previous, Position(x=previous.x, y=previous.y + 1)),
            'test:nested', feet=5, intent=engine._active_intent,
            ignore_oa_from=tuple(engine.state.actors))
        seen.append(('nested', movement_steps.opportunity_exempt(engine, target, LEE)))
        return None

    def entry(engine, mover, previous, nxt, intent):
        if mover.entity_id != ME:
            return None
        protected = movement_steps.opportunity_exempt(engine, mover, LEE)
        seen.append(('entry', protected))
        if not protected:
            threat = engine.state.actors[LEE]
            threat.reaction_available = False
            engine._resolve_attack_spec(threat, mover,
                {'attack_bonus': 100, 'reach_ft': 100, 'damage': DiceSpec(count=1, sides=4),
                 'damage_type': 'BLUDGEONING'}, intent, source_definition_id='test:entry')
        if outcome == 'stop':
            return {'stop': True, 'source_id': 'test:stop', 'label': 'The route stops here.'}
        if outcome == 'error':
            raise ValueError('test entry failure')
        if outcome == 'pause' and not paused:
            paused.append(True)
            raise ext.ControllerPause({'test': 'pause'})
        return None

    install(monkeypatch, 'before_attack', nested)
    install(monkeypatch, 'movement_step', entry)
    bundle = compile_character(_sheet([]), actor_id=ME)
    session = CombatService(ROOT, tmp_path).persistence.create_match(match_seed='LOCK27-POLICY',
        typed_bundles=(bundle,), roster_setup={'primary_actor_ids': [ME, AN, LEE],
        'team_by_actor': {ME: 'team:a', AN: 'team:b', LEE: 'team:b'},
        'starting_positions': {ME: {'x': 5, 'y': 6}, AN: {'x': 6, 'y': 6},
                               LEE: {'x': 10, 'y': 6}}})
    while session.engine.state.current_actor_id != ME:
        session = _execute(tmp_path, session.match_id)
    return session, seen


@pytest.mark.parametrize('outcome', [None, 'stop'])
def test_native_nested_step_keeps_outer_selective_protection(tmp_path, monkeypatch, outcome):
    session, seen = _setup(tmp_path, monkeypatch, outcome)
    use = ReactionDecision(checkpoint='LEAVE_REACH', reactor_id=AN,
        reaction_source_id=SYSTEM_OPPORTUNITY, selection='USE')
    cold = _execute(tmp_path, session.match_id, lambda c: c.source_definition_id == SOURCE, (use,))
    assert ('nested', True) in seen
    assert ('entry', True) in seen
    assert all(protected for _, protected in seen)
    assert any(e.event_type == 'REACTION_RESOLVED' and e.actor_id == AN
               and e.source_definition_id == SYSTEM_OPPORTUNITY for e in cold.engine.events)
    assert not any(e.source_definition_id == 'test:entry' for e in cold.engine.events)
    assert cold.engine.state.actors[LEE].reaction_available
    assert cold.engine.state.actors[ME].position.x == (4 if outcome else 3)
    assert getattr(cold.engine, '_movement_step_oa', None) is None
    assert cold.verify()['status'] == 'PASS'


@pytest.mark.parametrize('outcome', ['error', 'pause'])
def test_native_policy_restores_enclosing_snapshot_on_aborted_intent(tmp_path, monkeypatch, outcome):
    session, seen = _setup(tmp_path, monkeypatch, outcome)
    engine = session.engine
    actor = engine.state.actors[ME]
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == SOURCE)
    from combat.gate2_runtime_models import ActionIntent
    intent = ActionIntent(intent_id='lock27:abort', decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=ME, target_ids=candidate.target_ids)
    before = engine.state.model_dump(mode='json')
    snapshot = {'actor_id': ME, 'ignore': ('outer',)}
    engine._movement_step_oa = snapshot
    with movement_steps.opportunity_policy(engine, actor, ('outer',)):
        with pytest.raises((Exception, ext.ControllerPause)):
            session.mechanical.execute_intent(intent)
        assert engine._movement_step_oa is snapshot
        assert engine._movement_ignore_oa == (ME, ('outer',))
    assert engine.state.model_dump(mode='json') == before
    cold = CombatService(ROOT, tmp_path)._load_session(session.match_id)
    if outcome == 'error':
        assert cold.engine.state.model_dump(mode='json') == before
    else:
        # A persisted PREPARE resumes after the test-only choice is answered.
        assert cold.engine.state.actors[ME].position == Position(x=3, y=6)
    assert getattr(cold.engine, '_movement_step_oa', None) is None
    assert cold.mechanical.replay()['status'] == 'PASS'


def test_existing_adapter_scope_still_needs_native_nested_restoration(tmp_path, monkeypatch):
    """Even an adapter's outer finally restores too late for the next entry.

    This is also run against base with only the shared policy helper copied in,
    isolating the locked native wrapper from introducing the helper itself.
    """
    session, seen = _setup(tmp_path, monkeypatch)
    original = ext.effects()['test_lock27_route']

    def adapter(ctx, row):
        with movement_steps.opportunity_policy(ctx.engine, ctx.actor, (LEE,)):
            original(ctx, row)

    monkeypatch.setitem(ext.effects(), 'test_lock27_route', adapter)
    use = ReactionDecision(checkpoint='LEAVE_REACH', reactor_id=AN,
        reaction_source_id=SYSTEM_OPPORTUNITY, selection='USE')
    cold = _execute(tmp_path, session.match_id, lambda c: c.source_definition_id == SOURCE, (use,))
    assert ('nested', True) in seen, 'nested native movement stripped the enclosing policy snapshot'
    assert ('entry', True) in seen
    assert not any(e.source_definition_id == 'test:entry' for e in cold.engine.events)
    assert cold.engine.state.actors[LEE].reaction_available
    assert cold.verify()['status'] == 'PASS'
