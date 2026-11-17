"""Additive reductions compose at the final checkpoint, through saved sessions."""
import pytest

from combat import ext
from combat.gate2_runtime_models import ActionDefinition, ActionIntent
from combat.gate5_service import CombatService
from tests.test_auto_docket import ROOT, ME
from tests.test_lock_choices import install
from tests.test_lock26_movement_concentration_seams import _execute, _match


SOURCE = 'action:test.lock27.damage'


def _setup(tmp_path, monkeypatch, answers, amount=12, temp=0):
    install(monkeypatch, 'compile_actions', lambda info: [ActionDefinition(
        source_definition_id=SOURCE, display_name='Test damage', owner_id=info['actor_id'],
        economy='NONE', resolution_kind='TYPED', target_kind='SELF',
        parameters={'typed': {'source': SOURCE, 'numbers': info['numbers'], 'effects': [
            *([{'type': 'temp_hp', 'flat': temp, 'applies_to': 'self'}] if temp else []),
            {'type': 'damage', 'flat': amount, 'damage_types': ['FORCE'], 'applies_to': 'self'}]}})])
    seen = []
    def provider(answer):
        def respond(engine, target, defended, *args):
            seen.append(defended)
            return answer(engine, target, defended) if callable(answer) else answer
        return respond
    install(monkeypatch, 'final_damage', provider(answers[0]))
    for answer in answers[1:]:
        ext._HOOKS['final_damage'].append(provider(answer))
    mid, session = _match(tmp_path, 'LOCK27-DAMAGE')
    return mid, session, seen


@pytest.mark.parametrize('answers,expected', [
    ([{'reduction': 2}, {'reduction': 3}], 7),
    ([{'amount': 8}, {'reduction': 2}, {'reduction': 3}], 3),
    ([{'amount': 8, 'reduction': 2}, {'amount': 10, 'reduction': 3}], 3),
    ([{'reduction': 12}, {'reduction': 12}], 0),
    ([{'amount': 8}, {'amount': 10}], 8),
    ([None], 12),
])
def test_reductions_sum_once_after_minimum_amount(tmp_path, monkeypatch, answers, expected):
    mid, session, seen = _setup(tmp_path, monkeypatch, answers)
    before = session.engine.state.actors[ME].current_hp
    cold = _execute(tmp_path, mid, lambda c: c.source_definition_id == SOURCE)
    assert cold.engine.state.actors[ME].current_hp == before - expected
    packet = next(e for e in reversed(cold.engine.events) if e.event_type == 'DAMAGE_COMMITTED')
    assert packet.payload['reduced_to'] == expected
    assert seen and set(seen) == {12}
    assert cold.verify()['status'] == 'PASS'


def test_reductions_precede_hp_floor_and_temporary_hp(tmp_path, monkeypatch):
    answers = [{'amount': 8, 'reduction': 2}, {'reduction': 3},
               lambda engine, target, defended: {'hp_floor': target.current_hp - 1}]
    mid, session, seen = _setup(tmp_path, monkeypatch, answers, temp=1)
    before = session.engine.state.actors[ME].current_hp
    cold = _execute(tmp_path, mid, lambda c: c.source_definition_id == SOURCE)
    target = cold.engine.state.actors[ME]
    assert target.current_hp == before - 1
    assert target.temporary_hp == 0
    packet = next(e for e in reversed(cold.engine.events) if e.event_type == 'DAMAGE_COMMITTED')
    assert packet.payload['reduced_to'] == 2


@pytest.mark.parametrize('answer', [{'reduction': -1}, {'reduction': True},
    {'reduction': 13}, {'reduction': 1.0}, {'reduction': '1'}, {'reduction': None},
    {'reduction': 1, 'unknown': 0}])
def test_invalid_reduction_rolls_back_before_commit_and_reloads(tmp_path, monkeypatch, answer):
    mid, session, seen = _setup(tmp_path, monkeypatch, [answer])
    candidate = next(c for c in session.engine.legal_candidates() if c.source_definition_id == SOURCE)
    before = session.engine.state.model_dump(mode='json')
    intent = ActionIntent(intent_id='lock27:invalid', decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=ME, target_ids=candidate.target_ids)
    with pytest.raises(Exception, match='final_damage'):
        session.mechanical.execute_intent(intent)
    assert session.engine.state.model_dump(mode='json') == before
    cold = CombatService(ROOT, tmp_path)._load_session(mid)
    assert cold.engine.state.model_dump(mode='json') == before
    assert cold.mechanical.replay()['status'] == 'PASS'


def test_zero_damage_allows_only_zero_reduction(tmp_path, monkeypatch):
    mid, session, seen = _setup(tmp_path, monkeypatch, [{'reduction': 0}], amount=0)
    before = session.engine.state.actors[ME].current_hp
    cold = _execute(tmp_path, mid, lambda c: c.source_definition_id == SOURCE)
    assert cold.engine.state.actors[ME].current_hp == before
    assert seen and set(seen) == {0}
