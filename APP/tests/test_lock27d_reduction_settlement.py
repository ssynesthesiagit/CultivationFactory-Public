"""Test-only consumers of final reduction settlement; no Wax implementation."""
import pytest

from combat import ext
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
from tests.test_auto_docket import ROOT, ME
from tests.test_lock_choices import install
from tests.test_lock26_movement_concentration_seams import _execute
from tests.test_lock27_additive_damage import SOURCE, _setup


def consumer(name, reduction, failure=None, trace=None):
    def respond(engine, target, defended):
        def settle(applied):
            if trace is not None:
                trace.append((name, applied))
            if applied > 0:
                engine._spend_resource(target, 'resource:core.qi', 1, SOURCE)
            engine._append_event('PASSIVE_TRIGGERED', SOURCE, actor_id=target.entity_id,
                payload={'log': 'Test reduction settled.', 'name': name,
                         'applied': applied, 'spent': int(applied > 0)})
            if failure == 'error':
                raise ValueError('test settlement failure')
            if failure == 'pause':
                raise ext.ControllerPause('test settlement choice')
            if failure == 'return':
                return applied
        return {'reduction': min(defended, reduction), 'settle': settle}
    return respond


@pytest.mark.parametrize('answers,expected,damage', [
    ([consumer('first', 2), consumer('second', 3)], [('first', 2), ('second', 3)], 7),
    ([consumer('first', 9), consumer('second', 9)], [('first', 9), ('second', 3)], 0),
    ([consumer('second', 9), consumer('first', 9)], [('second', 9), ('first', 3)], 0),
    ([{'amount': 0}, consumer('unused', 4)], [('unused', 0)], 0),
    ([consumer('unused', 4), {'amount': 0}], [('unused', 0)], 0),
    ([{'reduction': 10}, consumer('last', 4)], [('last', 2)], 0),
    ([consumer('zero', 0)], [('zero', 0)], 12),
    ([lambda e, t, d: {'hp_floor': t.current_hp}, consumer('floor', 4)], [('floor', 0)], 0),
    ([consumer('floor', 9), lambda e, t, d: {'hp_floor': t.current_hp - 4},
      consumer('last', 9)], [('floor', 1), ('last', 3)], 0),
])
def test_settlement_persists_order_effective_contribution_and_spending(
        tmp_path, monkeypatch, answers, expected, damage):
    mid, session, _ = _setup(tmp_path, monkeypatch, answers)
    before = session.engine.state.actors[ME].current_hp
    before_qi = session.engine.state.actors[ME].resources['resource:core.qi']
    # _execute commits through the cold-loaded session and mechanically replays.
    cold = _execute(tmp_path, mid, lambda c: c.source_definition_id == SOURCE)
    rows = [e for e in cold.engine.events if e.source_definition_id == SOURCE and 'applied' in e.payload]
    assert [(e.payload['name'], e.payload['applied']) for e in rows] == expected
    assert [e.payload['spent'] for e in rows] == [int(applied > 0) for _, applied in expected]
    assert cold.engine.state.actors[ME].current_hp == before - damage
    assert cold.engine.state.actors[ME].resources['resource:core.qi'] == before_qi - sum(
        int(applied > 0) for _, applied in expected)
    committed = next(e for e in reversed(cold.engine.events) if e.event_type == 'DAMAGE_COMMITTED')
    assert committed.payload['reduced_to'] == damage
    assert all(e.sequence < committed.sequence for e in rows)
    assert cold.verify()['status'] == 'PASS'


@pytest.mark.parametrize('answers,expected', [
    ([None], 12), ([{'amount': 8}, {'amount': 10}], 8),
    ([{'reduction': 2}, {'reduction': 3}], 7),
])
def test_omitted_settlement_is_inert(tmp_path, monkeypatch, answers, expected):
    mid, session, _ = _setup(tmp_path, monkeypatch, answers)
    before = session.engine.state.actors[ME].current_hp
    cold = _execute(tmp_path, mid, lambda c: c.source_definition_id == SOURCE)
    assert cold.engine.state.actors[ME].current_hp == before - expected
    assert not any(e.source_definition_id == SOURCE and 'applied' in e.payload for e in cold.engine.events)
    assert cold.verify()['status'] == 'PASS'


@pytest.mark.parametrize('failure', ['error', 'pause', 'return', 'invalid_later', 'not_callable', 'no_reduction'])
def test_settlement_contract_failures_rollback_and_reload(tmp_path, monkeypatch, failure):
    trace = []
    answers = [consumer('first', 2, trace=trace), consumer('last', 3, failure, trace=trace)]
    if failure == 'invalid_later':
        answers.append({'reduction': True})
    if failure == 'not_callable':
        answers.append({'reduction': 1, 'settle': 0})
    if failure == 'no_reduction':
        answers.append({'settle': lambda applied: None})
    mid, session, _ = _setup(tmp_path, monkeypatch, answers)
    candidate = next(c for c in session.engine.legal_candidates() if c.source_definition_id == SOURCE)
    before = session.engine.state.model_dump(mode='json')
    events = [e.model_dump(mode='json') for e in session.engine.events]
    intent = ActionIntent(intent_id='lock27d:invalid', decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=ME, target_ids=candidate.target_ids)
    error = ext.ControllerPause if failure == 'pause' else ValueError
    with pytest.raises(error):
        session.mechanical.execute_intent(intent)
    assert trace == ([] if failure in ('invalid_later', 'not_callable', 'no_reduction')
                     else [('first', 2), ('last', 3)])
    assert session.engine.state.model_dump(mode='json') == before
    assert [e.model_dump(mode='json') for e in session.engine.events] == events
    if failure == 'pause':
        # A PREPARE survives the pause; answer the test-only choice before cold recovery.
        install(monkeypatch, 'final_damage', lambda e, t, d, *args: consumer('first', 2)(e, t, d))
        ext._HOOKS['final_damage'].append(lambda e, t, d, *args: consumer('last', 3)(e, t, d))
    cold = CombatService(ROOT, tmp_path)._load_session(mid)
    if failure == 'pause':
        target = cold.engine.state.actors[ME]
        assert target.current_hp == before['actors'][ME]['current_hp'] - 7
        assert target.resources['resource:core.qi'] == before['actors'][ME]['resources']['resource:core.qi'] - 2
        rows = [e for e in cold.engine.events if e.source_definition_id == SOURCE and 'applied' in e.payload]
        assert [(e.payload['name'], e.payload['applied']) for e in rows] == [('first', 2), ('last', 3)]
    else:
        assert cold.engine.state.model_dump(mode='json') == before
        assert [e.model_dump(mode='json') for e in cold.engine.events] == events
    assert cold.mechanical.replay()['status'] == 'PASS'
