"""Review F9RSC finding 1: an anonymous save-mode grant keeps its own receipt.

A bare Advantage reply (Stand Against the Calamity style aura) and a named Advantage
source of the same kind both act on one Dexterity save. Both must stay listed on the
roll after a table commit and cold reload, not only the first named one.
"""
import pytest

from combat import ext
from combat.gate5_service import CombatService
from combat.history_feed import _roll_text
from tests.h1_support import ROOT
from tests.test_hidden_targeting import table_fight, turn, LEFT, RIGHT
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install


@pytest.mark.parametrize('bare_first', [True, False])
def test_anonymous_and_named_save_advantage_both_listed_through_reload(tmp_path, monkeypatch, bare_first):
    ext.effects()
    anonymous = lambda engine, subject, *args: 'ADVANTAGE' if subject.entity_id == LEFT else None
    named = lambda engine, subject, *args: ({'mode': 'ADVANTAGE', 'effect': 'Dodge', 'owner': 'Left',
                                             'why': 'the Dodge action helps this saving throw'}
                                            if subject.entity_id == LEFT else None)
    hooks = [anonymous, named] if bare_first else [named, anonymous]
    monkeypatch.setitem(ext._HOOKS, 'save_mode', hooks)
    combat, table, mid = table_fight(tmp_path, left_at=(3, 11), right_at=(4, 11))
    turn(table, mid, LEFT)
    errors = []

    def resolve(engine, kind, kwargs):
        if kind != 'HOLD_POSITION_COMMITTED' or kwargs.get('actor_id') != LEFT:
            return
        engine._roll_save(engine.state.actors[LEFT], 'DEX', 12, 'test:save')

    def checked_resolve(*args):
        try:
            resolve(*args)
        except Exception:
            import traceback
            errors.append(traceback.format_exc())
            raise
    install(monkeypatch, 'event', checked_resolve)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    assert not errors, errors
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    payload = next(e.payload for e in reversed(loaded.engine.events) if e.event_type == 'SAVE_ROLLED')
    assert payload['mode'] == 'ADVANTAGE'
    receipts = payload['mode_sources']
    advantage = [row for row in receipts if row['kind'] == 'advantage']
    assert {row['effect'] for row in advantage} >= {'Dodge', 'Save-specific effect'}, receipts
    assert len(receipts) == len({tuple(sorted(row.items())) for row in receipts})
    assert 'Dodge' in _roll_text(payload)
    roll = next(r for r in loaded.engine.rolls if r.roll_id == payload['roll_id'])
    assert roll.mode_sources == receipts
