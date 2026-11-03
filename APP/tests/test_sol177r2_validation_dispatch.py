"""Pin fresh targeted and full-fallback dispatch, including a tiny menu.

Paired F profiles do not support replacing targeted validation with a menu-size
heuristic: even three-candidate menus benefited. These tests assert mechanics
and dispatch only; timings belong in the isolated evidence protocol.
"""
import sys

import pytest

from combat.canonical import canonical_bytes
from combat.gate2_runtime_models import Position
from tests.h1_support import duel
from tests.test_sol177r1_targeted_validation import intent_for


def observe_generation(engine, intent):
    """Observe the native boundary without replacing an engine method."""
    calls = []

    def observed(frame, event, arg):
        if event == 'call' and frame.f_code.co_name == '_generate_legal_candidates' \
                and frame.f_code.co_filename.endswith('/gate2_engine.py') \
                and frame.f_locals.get('self') is engine:
            calls.append(frame.f_locals.get('intent'))

    previous = sys.getprofile()
    try:
        sys.setprofile(observed)
        result = engine.candidates_for_intent(intent)
    finally:
        sys.setprofile(previous)
    return result, calls


def test_tiny_menu_chosen_intent_uses_one_fresh_targeted_pass():
    engine = duel([])
    actor = engine.state.actors[engine.state.current_actor_id]
    actor.movement_remaining_ft = 0
    actor.action_available = actor.bonus_action_available = False
    full = engine._generate_legal_candidates()
    assert 1 < len(full) <= 3
    chosen = next(c for c in full if c.kind.value == 'END_TURN')
    intent = intent_for(chosen)
    result, calls = observe_generation(engine, intent)
    assert calls == [intent]
    assert canonical_bytes([c.model_dump(mode='json') for c in result]) == canonical_bytes([chosen.model_dump(mode='json')])


@pytest.mark.parametrize('missing_identity', [False, True])
def test_malformed_hint_and_missing_identity_use_fresh_full_fallback(missing_identity):
    engine = duel([])
    full = engine._generate_legal_candidates()
    chosen = next(c for c in full if c.kind.value == 'MOVE')
    intent = intent_for(chosen).model_copy(update={'destination': Position(x=999, y=999)})
    if missing_identity:
        intent = intent.model_copy(update={'candidate_id': 'candidate:illegal'})
    expected = tuple(c for c in full if c.candidate_id == intent.candidate_id)
    result, calls = observe_generation(engine, intent)
    assert calls == [intent, None]
    assert canonical_bytes([c.model_dump(mode='json') for c in result]) == canonical_bytes([c.model_dump(mode='json') for c in expected])
