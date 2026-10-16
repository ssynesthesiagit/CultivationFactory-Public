"""Guard both sides of the round19/native-lock3 save-context merge.

Existing R3i and Hunt5 table tests exercise choices, commit/reload and replay.
These checks catch a merge that discards either the final-outcome save scope
or the native metadata needed by roll rewrites and Court's shared bonus hook.
"""
from combat.typed_executor import active_save_pending
from tests.test_lock_choices import install, intent
from tests.test_auto_tabik import _engine
from tests import test_riders_lane3 as L


def test_typed_save_retains_pending_scope_and_native_named_context(monkeypatch):
    seen = []

    def observe(engine, roll, request):
        frame = engine.d20_context(roll)
        if frame and frame['kind'] == 'save':
            seen.append((frame, active_save_pending(engine, frame['source_id'], roll.actor_id)))

    install(monkeypatch, 'd20_result', observe)
    engine, _ = L._beauty_cast('beauty_that_ends_war', 'Beauty That Ends War')
    frames = [(frame, pending) for frame, pending in seen if 'charmed' in frame.get('named', [])]
    assert frames
    for frame, pending in frames:
        assert pending
        assert frame['source_actor_id'] == L.ME
        assert frame['target_id'] == L.H.FOE
        assert frame['ability'] == 'WIS'
        assert frame['dc'] == 50
        assert not active_save_pending(engine, frame['source_id'], frame['target_id'])
    assert engine.d20_context() is None


def test_turn_start_bonus_uses_native_intent_without_stale_transport(monkeypatch):
    seen = []
    install(monkeypatch, 'd20_bonus', lambda engine, roll, request: seen.append(request))

    def roll_at_start(engine, actor):
        engine.roller.d20(modifier=0, actor_id=actor.entity_id, reason='CHECK:integration:DEX')

    install(monkeypatch, 'turn_start', roll_at_start)
    engine, _ = _engine([])
    seen.clear()  # initialization has no accepted intent
    request = intent(engine)
    engine.execute_intent(request)
    assert seen == [request]
    assert engine._active_intent is None
    assert not getattr(engine, '_active_turn_advancing', False)
    assert not hasattr(engine, '_ext_turn_intent')
    seen.clear()
    engine.end_turn('test:system-transition')
    assert seen == [None]
