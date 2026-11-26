"""Review F8R finding 1: Mageguard's Concentration reply names a Disadvantage mode.

The owned reach reply must be consumed by the shared save-mode path without a
ValueError, and the roll must keep Mageguard's reason as a receipt.
"""
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, settle
from tests.hunt15_support import turn

MAGE = 'TAL_GUARDIAN_MAGEGUARD'


def test_mageguard_concentration_save_within_reach_is_disadvantage_with_reason(tmp_path):
    effects = [{'type': 'guardian_challenge', 'applies_to': 'target'}]
    c, t, m = fight(tmp_path, [MAGE], left_score=50, right_score=214,
                    right_talents=['tianxia.talent.poison.miasma_form'], prepare=effects,
                    positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}},
                    cause_target='SELF',
                    cause=[{'type': 'save', 'ability': 'con', 'dc': 'technique_save_dc', 'applies_to': 'self',
                            'on_fail': [], 'on_success': []},
                           {'type': 'damage', 'flat': 1, 'damage_types': ['fire'], 'applies_to': 'self'}])
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, 'Miasma Form', a))
    turn(t, m, LEFT)
    settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    turn(t, m, RIGHT)
    before = len(reload(c, m).events)
    settle(lambda a: act(t, m, 'Cause', a))
    e = reload(c, m)
    concentration = [v for v in e.events[before:]
                     if v.event_type == 'SAVE_ROLLED' and v.source_definition_id == 'system:combat.concentration']
    assert concentration, 'expected a Concentration save roll'
    payload = concentration[-1].payload
    assert payload['mode'] == 'DISADVANTAGE'
    holder = e.state.actors[LEFT].display_name
    assert any(s['effect'] == 'Mageguard' and s['kind'] == 'disadvantage' and s['owner'] == holder
               and 'melee reach' in s['why'] for s in payload['mode_sources']), payload['mode_sources']
