"""Walking forecasts and observer-only facts coexist in native decision contexts."""
from copy import deepcopy

import pytest

from combat import ext
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from tests.h1_support import ME
from tests.test_aiwalk1 import walking_duel


@pytest.mark.parametrize('for_ai', [False, True])
def test_observer_information_survives_walk_annotations(monkeypatch, for_ai):
    engine, policy = walking_duel()
    before = deepcopy(engine.state.model_dump(mode='json'))
    events = deepcopy(engine.events)
    fact = {'ability': 'Observation', 'kind': 'direction', 'direction': 'east'}
    observers = []

    def private_information(view, observer):
        assert view is engine
        observers.append(observer.entity_id)
        return [fact] if observer.entity_id == ME else []

    ext._load()
    monkeypatch.setitem(ext._HOOKS, 'observer_information', [private_information])
    context = build_decision_context(engine, policy, for_ai=for_ai)

    assert context.information == (fact,)
    assert context.model_dump(mode='json')['information'] == [fact]
    assert observers == [ME]
    assert any(c.metadata.get('walk_attack') for c in context.legal_candidates) == for_ai
    if for_ai:
        choice = LocalDeterministicController().choose_primary_action(context)
        assert choice.intent.destination is not None
        engine.execute_intent(choice.intent)
        followup = build_decision_context(engine, policy, for_ai=True)
        assert followup.information == (fact,)
        choice = LocalDeterministicController().choose_primary_action(followup)
        selected = next(c for c in followup.legal_candidates
                        if c.candidate_id == choice.intent.candidate_id)
        assert selected.source_definition_id.endswith('strong_blade')
    else:
        assert engine.state.model_dump(mode='json') == before
        assert engine.events == events
