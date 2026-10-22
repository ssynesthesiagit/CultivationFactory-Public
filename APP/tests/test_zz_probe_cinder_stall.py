"""TEMPORARY probe for the automatic-foe stall; removed before merge."""
import json
from combat.gate5_service import CombatService
from tests.test_survivor_cinder_breath import setup, OWNER, ALLY, FOE


def test_probe_auto_foe_trail(tmp_path):
    modes = {OWNER: 'LOCAL_AUTO', ALLY: 'MANUAL', FOE: 'LOCAL_AUTO'}
    combat, table, mid = setup(tmp_path, modes=modes)
    rows = []
    for step in range(12):
        menu = table.state(mid)['menu']
        engine = combat._load_session(mid).engine
        rows.append(('MENU', step, menu.get('actor_id'), 'end_turn' in menu, engine.state.current_actor_id,
                     [(e.event_type, e.actor_id, str(e.payload)[:120]) for e in engine.events[-3:]]))
        if menu.get('actor_id') == OWNER:
            break
        result = table.auto_step(mid, 0, [])
        rows.append(('AUTO', result['status'], (result.get('reaction') or {}).get('context', {}).get('reaction_source_id')))
    assert False, json.dumps(rows, indent=1, default=str)
