"""Countermeasure adds a source, preserving all prior d20 cancellation sources."""
import pytest
from combat import ext, native_reactions
from tests.test_lock13_native_opportunity import fight, move, checked, AN, ME, OA
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import on_hold, HOLD
from tests.test_lock_choices import install


@pytest.mark.parametrize('sources', ['dodge', 'checkpoint', 'both_checkpoints'])
def test_countermeasure_does_not_override_cancelled_native_roll(monkeypatch, tmp_path, sources):
    svc, table, mid = fight(tmp_path)
    def prepare(engine):
        if sources != 'both_checkpoints':
            engine._add_modifier(engine.state.actors[AN], 'test:advantage', 'attack_mode', 'SET',
                                 'ADVANTAGE', 'NEXT_ATTACK', expires_on=None)
        if sources == 'dodge':
            engine._apply_condition(engine.state.actors[ME], 'condition:core.dodge',
                                    'test:dodge', ME, expires_on='START_OF_SELF_NEXT_TURN')
    on_hold(monkeypatch, prepare)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    if sources != 'dodge':
        install(monkeypatch, 'before_attack', lambda *args: {'mode': 'DISADVANTAGE'})
        if sources == 'both_checkpoints':
            monkeypatch.setitem(ext._HOOKS, 'before_attack', [
                lambda *args: {'mode': 'ADVANTAGE'}, lambda *args: {'mode': 'DISADVANTAGE'}])
    prompts = move(svc, table, mid)
    assert any(p['reaction'] == 'Charged Countermeasure' for p in prompts)
    engine = checked(svc, tmp_path, mid)
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.source_definition_id == OA]
    assert len(attacks) == 1 and attacks[0].payload['mode'] == 'NORMAL'


def test_native_mode_query_is_inert_outside_accepted_scope():
    from types import SimpleNamespace
    engine = SimpleNamespace()
    assert native_reactions.roll_mode(engine, 'a', 'b', 'NORMAL') == 'NORMAL'
