"""Healing sufficiency stays with the GM; committed Action removal still works."""
import pytest

from combat.ext.sniper_lines import HINDERED
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload, turn

HINDERING = 'TAL_SNIPER_HINDERING_PROJECTILE'
BOW = {'items': [{'item_id': 'tianxia.mortal.weapon.gong_jian',
                  'name': 'Gong Jian (Bow and Arrow)', 'quantity': 1}]}


@pytest.mark.parametrize('healing', [0, 1, 10000])
def test_hindering_projectile_healing_after_saved_shot(tmp_path, healing):
    combat, table, mid = fight(tmp_path, [HINDERING, 'TAL_SNIPER_SNIPER_TRAINING'], left_kit=BOW, left_score=30, right_score=2, positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 6, "y": 6}},
        cause=[{'type': 'healing', 'flat': healing, 'applies_to': 'self'}])
    assert act(table, mid, 'Snipe Shot: Gong Jian (Bow and Arrow) + Hindering Projectile', target_id=RIGHT)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert any(c.condition_id == HINDERED for c in engine.state.actors[RIGHT].conditions.values())
    turn(table, mid, RIGHT)
    before = reload(combat, mid).state.actors[RIGHT].current_hp
    assert act(table, mid, 'Cause')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert engine.state.actors[RIGHT].current_hp == min(1000, before + healing)
    # "sufficient healing" has no numeric threshold in the owner rules.
    assert any(c.condition_id == HINDERED for c in engine.state.actors[RIGHT].conditions.values())
    assert any(e.event_type == 'GM_RIDER' and 'sufficiently seals' in e.payload.get('rider', '') for e in engine.events)


def test_hindering_projectile_action_removal_survives_reload(tmp_path):
    combat, table, mid = fight(tmp_path, [HINDERING, 'TAL_SNIPER_SNIPER_TRAINING'], left_kit=BOW, left_score=30, right_score=2, positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 6, "y": 6}})
    assert act(table, mid, 'Snipe Shot: Gong Jian (Bow and Arrow) + Hindering Projectile', target_id=RIGHT)['status'] == 'COMMITTED'
    reload(combat, mid)
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Remove the projectile')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert not any(c.condition_id == HINDERED for c in engine.state.actors[RIGHT].conditions.values())
    assert not engine.state.actors[RIGHT].action_available


def test_healing_without_a_lodged_projectile_is_inert(tmp_path):
    combat, table, mid = fight(tmp_path,
        prepare=[{'type': 'damage', 'flat': 10, 'damage_type': 'FORCE', 'applies_to': 'target'}],
        cause=[{'type': 'healing', 'flat': 1, 'applies_to': 'self'}])
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Cause')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert engine.state.actors[RIGHT].current_hp == 991
    assert not any('lodged wounds' in str(e.payload) for e in engine.events)
