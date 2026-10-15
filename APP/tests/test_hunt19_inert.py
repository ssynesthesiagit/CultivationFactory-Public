"""Bounded AI event-byte comparison for characters without hunt19 abilities."""
import json

from combat import ext
from tests.hunt19_support import fight, reload
from tests.test_lock2_persistence import act


def test_unowned_plugins_leave_ai_event_bytes_unchanged(tmp_path, monkeypatch):
    def play(root):
        combat, table, mid = fight(root, [], mode='LOCAL_AUTO', ask=False)
        for _ in range(8):
            state = table.state(mid)
            result = act(table, mid, 'end') if state['menu'].get('manual') else table.auto_step(mid, state['last_sequence'])
            assert result['status'] == 'COMMITTED'
        engine = reload(combat, root, mid)
        return json.dumps([e.model_dump(mode='json') for e in engine.events], sort_keys=True, separators=(',', ':'))

    enabled = play(tmp_path / 'enabled')
    modules = {'combat.ext.creature_targeting', 'combat.ext.ward_summaries'}
    names = {'accomplice_available', 'accomplice_recipient', 'accomplice_text', 'meat_shield_decision_text'}
    # Remove only this lane's registered extensions, never patch engine/core methods.
    for point, handlers in list(ext._HOOKS.items()):
        monkeypatch.setitem(ext._HOOKS, point, [h for h in handlers if h.__module__ not in modules and h.__name__ not in names])
    assert play(tmp_path / 'disabled') == enabled
