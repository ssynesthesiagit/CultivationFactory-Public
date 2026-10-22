"""TEMPORARY probe for the automatic-foe stall; removed before merge."""
import json
from combat.gate5_service import CombatService
from tests import worker2_support as w2
from tests.test_survivor_cinder_breath import setup, OWNER, ALLY, FOE


def test_probe_auto_foe_trail(tmp_path, monkeypatch):
    monkeypatch.setattr(w2, 'turn', lambda *a, **k: None)
    modes = {OWNER: 'LOCAL_AUTO', ALLY: 'MANUAL', FOE: 'LOCAL_AUTO'}
    combat, table, mid = setup(tmp_path, modes=modes)
    rows = []
    for step in range(40):
        menu = table.state(mid)['menu']
        if menu.get('actor_id') == OWNER:
            rows.append(('OWNER_TURN', step))
            break
        result = table.auto_step(mid, 0, [])
        engine = combat._load_session(mid).engine
        ev = [(e.event_type, str(e.payload)[:160]) for e in engine.events[-4:]]
        rows.append((step, menu.get('actor_id'), 'end_turn' in menu, result['status'], ev))
    assert False, json.dumps(rows, indent=1, default=str)
