"""Native d20 context identifies the actual roll without instance method patches."""
import pytest

from combat.ext import ControllerPause
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
from tests.test_auto_tabik import _engine, ME, AN
from tests.test_lock_choices import install, intent


def test_save_context_includes_actual_source_and_dc_and_is_cleared(monkeypatch):
    seen = []
    install(monkeypatch, 'd20_result', lambda e, r, i: seen.append(e.d20_context(r)))
    engine, _ = _engine([])
    assert engine._roll_save.__func__ is Gate2Engine._roll_save
    engine._roll_save(engine.state.actors[AN], 'CON', 17, 'test:hazard',
                      roll_context={'source_actor_id': ME, 'named': ['damage:fire']})
    context, = seen
    assert {key: context[key] for key in ('kind', 'actor_id', 'target_id', 'ability', 'dc', 'source_id', 'source_actor_id')} == {
        'kind': 'save', 'actor_id': AN, 'target_id': AN, 'ability': 'CON', 'dc': 17,
        'source_id': 'test:hazard', 'source_actor_id': ME}
    assert context['named'] == ['damage:fire']
    assert engine.d20_context() is None


def test_attack_context_identifies_actual_target_and_cover(monkeypatch):
    seen = []
    install(monkeypatch, 'd20_result', lambda e, r, i: seen.append(e.d20_context(r)))
    engine, _ = _engine([], foe_at=(4, 6))
    actor, target = engine.state.actors[ME], engine.state.actors[AN]
    assert engine._resolve_attack_spec.__func__ is Gate2Engine._resolve_attack_spec
    request = intent(engine)
    engine._resolve_attack_spec(actor, target, {'range_ft': 50, 'attack_bonus': -100, 'declaration_cover': 5,
                                               'declaration_done': True}, request, source_definition_id='test:attack')
    context, = seen
    assert context['kind'] == 'attack' and context['actor_id'] == ME and context['target_id'] == AN
    assert context['source_actor_id'] == ME and context['source_id'] == 'test:attack'
    event = next(e for e in engine.events if e.event_type == 'ATTACK_ROLLED')
    assert context['ac'] == event.payload['target_ac']
    assert context['spec']['range_ft'] == 50
    assert engine.d20_context() is None


def test_nested_roll_context_is_restored_and_preview_does_not_share_mutable_stack():
    engine, _ = _engine([])
    outer = {'kind': 'check', 'actor_id': ME, 'skill': 'Athletics', 'dc': 18, 'source_id': 'test:escape'}
    with engine.d20_scope(outer):
        clone = CombatService._clone_engine(engine.source_root, engine)
        with clone.d20_scope({'kind': 'save', 'actor_id': AN, 'ability': 'DEX', 'dc': 12, 'source_id': 'test:child'}):
            assert clone.d20_context()['actor_id'] == AN
            assert engine.d20_context()['actor_id'] == ME
        assert clone.d20_context() is None
        assert engine.d20_context()['dc'] == 18
        with pytest.raises(ControllerPause):
            with engine.d20_scope({'kind': 'save', 'actor_id': AN, 'ability': 'CON', 'dc': 20, 'source_id': 'test:pause'}):
                raise ControllerPause('choose')
        assert engine.d20_context()['skill'] == 'Athletics'
    assert engine.d20_context() is None


def test_accepted_attack_context_identifies_triggering_action_and_actor(monkeypatch):
    seen = []
    install(monkeypatch, 'd20_result', lambda e, r, i: seen.append(e.d20_context(r)))
    engine, _ = _engine([], foe_at=(4, 6))
    candidate = next(c for c in engine.legal_candidates()
                     if c.kind == 'ACTION' and c.target_ids == (AN,) and '.weapon.' in c.source_definition_id)
    engine.execute_intent(ActionIntent(intent_id='test:context', decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=ME,
        target_ids=candidate.target_ids, destination=candidate.destination, option_ids=candidate.option_ids))
    context = next(row for row in seen if row['kind'] == 'attack')
    assert context['triggering_action_id'] == candidate.source_definition_id
    assert context['triggering_actor_id'] == ME
    assert engine.d20_context() is None and engine._active_action_source_id is None
