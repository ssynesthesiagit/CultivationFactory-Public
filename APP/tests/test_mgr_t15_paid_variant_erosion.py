"""A different paid Water Lash modifier cannot prepay Scouring Erosion."""
import pytest
from tests.test_mgr_t15_close_cutting_current import CUTTING, RIVER, OWNER, native, cold, settle

DISTANT = 'TAL_QIWEAVING_DISTANT_MODULATION'


@pytest.mark.parametrize('river,scour', [(False, True), (True, False), (True, True)])
def test_distant_modulation_does_not_pay_for_river(tmp_path, river, scour):
    owned = [CUTTING, DISTANT] + ([RIVER] if river else [])
    combat, table, mid = native(tmp_path, material='rope', owner_mids=owned, cl=5)
    combat, table, before = cold(tmp_path, mid)
    obj = before.state.objects['object:map.81']
    rows = [c for c in before.legal_candidates()
            if c.display_name.startswith('Water Lash') and 'Distant Modulation' in c.display_name
            and 'River Cuts the Gate' not in c.display_name and obj.object_id in c.target_ids]
    assert rows
    chosen = rows[0]
    first = len(before.events)
    state = table.state(mid)
    prompts = settle(lambda a: table.act(mid, chosen.candidate_id, chosen.decision_id,
                                        chosen.state_version, state['last_sequence'], a),
                     'SLASHING', scour)
    _, _, after = cold(tmp_path, mid)
    events = after.events[first:]
    assert next(e for e in events if e.event_type == 'ATTACK_ROLLED').payload['provisional_hit']
    asked = any(p['context'].get('reaction_source_id') == 'choice:needle.scouring_erosion' for p in prompts)
    assert asked is river
    applied = river and scour
    assert bool(after.state.objects[obj.object_id].component.get('scouring_erosion_until')) is applied
    assert bool([e for e in events if e.event_type == 'PASSIVE_TRIGGERED'
                 and (e.payload or {}).get('scouring_erosion')]) is applied
    rolled = next(e for e in events if e.event_type == 'DAMAGE_ROLLED').payload['total']
    damage = next(e for e in events if e.event_type == 'OBJECT_UPDATED' and 'damage' in e.payload)
    assert damage.payload['damage']['taken'] == (rolled * 2 if applied else rolled // 2)
    paid = before.state.actors[OWNER].resources['resource:core.qi'] - after.state.actors[OWNER].resources['resource:core.qi']
    assert paid == 1 + int(applied)
