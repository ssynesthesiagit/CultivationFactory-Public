"""One native flat save adjustment covers legacy, typed and Concentration rolls."""
import pytest

from combat.gate5_service import CombatService
from combat.typed_executor import Context, block_save
from tests.test_auto_tabik import _engine, ME, AN
from tests.test_lock_choices import install, intent
from tests.test_lock2_persistence import ROOT, table_match, act


@pytest.mark.parametrize('bonus', [None, 0, -2, 5])
@pytest.mark.parametrize('mode', [None, 'ADVANTAGE', 'DISADVANTAGE'])
def test_native_flat_bonus_changes_modifier_not_dc_or_draws(monkeypatch, bonus, mode):
    baseline, _ = _engine([], seed='LOCK4-SAVE')
    engine, _ = _engine([], seed='LOCK4-SAVE')
    before = baseline._roll_save(baseline.state.actors[AN], 'WIS', 17, 'test:hazard', extra_mode=mode)
    seen = []
    def adjust(e, actor, ability, dc, source, request):
        seen.append(e.d20_context())
        return bonus
    install(monkeypatch, 'save_bonus', adjust)
    after = engine._roll_save(engine.state.actors[AN], 'WIS', 17, 'test:hazard', extra_mode=mode)
    assert after.modifier == before.modifier + (bonus or 0) and after.total == before.total + (bonus or 0)
    assert after.dice == before.dice and after.discarded == before.discarded and after.mode == before.mode
    assert len(seen) == 1 and seen[0]['dc'] == 17 and seen[0]['ability'] == 'WIS'
    assert engine.d20_context() is None
    if not bonus:
        assert engine.state.model_dump(mode='json') == baseline.state.model_dump(mode='json')
        assert engine.events == baseline.events and engine.rolls == baseline.rolls


def test_bonus_does_not_overcome_automatic_failure(monkeypatch):
    install(monkeypatch, 'save_bonus', lambda *args: 100)
    engine, _ = _engine([])
    actor = engine.state.actors[AN]
    engine._apply_condition(actor, 'condition:typed.paralyzed', 'test:paralyzed', ME, expires_on='UNTIL_REMOVED')
    roll = engine._roll_save(actor, 'DEX', 10, 'test:save')
    assert roll.total == -1
    assert any(e.event_type == 'SAVE_AUTO_FAILED' for e in engine.events)


def test_typed_adjustment_and_native_bonus_each_apply_once(monkeypatch):
    install(monkeypatch, 'save', lambda *args: {'bonus': 2})
    install(monkeypatch, 'save_bonus', lambda *args: 3)
    engine, _ = _engine([])
    target = engine.state.actors[AN]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME)
    typed = {'source': 'test:typed', 'numbers': {'save_dc': 20}, 'range_ft': 60}
    ctx = Context(engine, engine.state.actors[ME], action, intent(engine), typed, [target], target)
    block_save(ctx, {'type': 'save', 'ability': 'WIS', 'on_fail': [], 'on_success': []})
    saved = next(e for e in engine.events if e.event_type == 'SAVE_ROLLED')
    assert saved.payload['dc'] == 18
    assert saved.payload['modifier'] == target.saving_throws.get('WIS', 0) + 3


@pytest.mark.parametrize('answer', [True, 1.5, '2', {'bonus': 2}])
def test_invalid_bonus_rejects_transaction_without_drawing(monkeypatch, answer):
    install(monkeypatch, 'save_bonus', lambda *args: answer)
    engine, _ = _engine([])
    before = engine.state.model_dump(mode='json'), list(engine.events), engine.roller.counter
    with pytest.raises(ValueError, match='save_bonus'):
        with engine._transaction('test:save', 'test:save', AN):
            engine._roll_save(engine.state.actors[AN], 'CON', 15, 'test:save')
    assert (engine.state.model_dump(mode='json'), engine.events, engine.roller.counter) == before


def test_concentration_bonus_survives_table_commit_reload_and_replay(monkeypatch, tmp_path):
    install(monkeypatch, 'save_bonus', lambda e, a, ability, dc, source, request: 30 if source == 'system:combat.concentration' else None)
    def concentrate_and_damage(e, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED':
            actor = e.state.actors[kwargs['actor_id']]
            e._start_concentration(actor, 'test:held-spell')
            e._commit_damage(actor, 4, 'UNTYPED', 'test:damage', actor.entity_id, e._active_intent, reaction_depth=0)
    install(monkeypatch, 'event', concentrate_and_damage)
    service, table, mid = table_match(tmp_path)
    actor_id = table.state(mid)['menu']['actor_id']
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    saved = next(e for e in loaded.engine.events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id == 'system:combat.concentration')
    assert saved.payload['modifier'] == loaded.engine.state.actors[actor_id].saving_throws.get('CON', 0) + 30
    assert saved.payload['success'] and loaded.engine.state.actors[actor_id].concentration is not None
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
