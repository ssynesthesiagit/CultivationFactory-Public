"""The accepted turn-ending intent owns choices throughout the turn transition."""
import pytest

from combat.ext import ControllerPause
from tests.test_auto_tabik import _engine
from tests.test_lock_choices import install, intent


@pytest.mark.parametrize('pause', [False, True])
def test_native_turn_start_has_advancing_intent_and_always_clears_it(monkeypatch, pause):
    seen = []
    def start(engine, actor):
        if engine._active_intent is None:
            return
        assert engine._active_turn_advancing
        seen.append(engine._active_intent)
        if pause:
            raise ControllerPause('choose at turn start')
    install(monkeypatch, 'turn_start', start)
    engine, _ = _engine([])
    request = intent(engine)
    if pause:
        with pytest.raises(ControllerPause):
            engine.execute_intent(request)
    else:
        engine.execute_intent(request)
    assert seen == [request]
    assert engine._active_intent is None
    assert not getattr(engine, '_active_turn_advancing', False)
    if not pause:
        engine.end_turn('test:system-transition')
        assert seen == [request]  # a later system transition never borrows this request


def test_ready_does_not_gain_new_turn_boundary_triggers(monkeypatch):
    from combat.prepared_actions import CONDITION
    from tests.test_lock2_prepared import setup, request
    from tests.test_auto_tabik import ME
    engine = setup(monkeypatch)
    held = next(c for c in engine.state.actors[ME].conditions.values() if c.condition_id == CONDITION)
    held.data['trigger'] = 'TURN_STARTED'
    engine.set_reaction_provider(lambda *args: pytest.fail('Ready gained a turn-boundary trigger'))
    candidate = next(c for c in engine.legal_candidates() if c.kind == 'END_TURN')
    engine.execute_intent(request(engine, candidate))
    assert engine.state.actors[ME].reaction_available
    assert held.instance_id in engine.state.actors[ME].conditions
