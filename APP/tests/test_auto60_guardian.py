"""Actual Guardian Focus maneuver receipts, ownership and Patrol lifecycle."""
import pytest
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, action_sender, settle
from tests.hunt15_support import turn
PATROL = 'GUARDIAN_BASE_PATROL_PRACTICE'
FOCUS = 'TAL_GUARDIAN_GUARDIAN_S_FOCUS'
SWIFT = 'TAL_GUARDIAN_SWIFT_GUARDIAN'
RESOURCE = 'resource:core.martial_focus'
LABEL = 'Patrol (Swift Guardian: Bonus Action; spend Martial Focus, your readiness point)'

@pytest.mark.parametrize('action', ['Grapple', 'Shove: Prone', 'Shove: Push 5 ft'])
@pytest.mark.parametrize('ai', [False, True])
def test_actual_successful_patrol_maneuver_restores_focus(tmp_path, action, ai):
    c, t, m = fight(tmp_path, [PATROL, FOCUS, SWIFT], left_score=50, left_kit={'items': []})
    settle(lambda a: act(t, m, LABEL, a))
    assert reload(c, m).state.actors[LEFT].resources[RESOURCE] == 0
    settle(action_sender(c, t, m, action, ai=ai, target_id=RIGHT))
    e = reload(c, m)
    assert any((v.event_type == 'SAVE_ROLLED' and v.payload['success'] is False for v in e.events))
    assert e.state.actors[LEFT].resources[RESOURCE] == 1
    assert e.state.actors[LEFT].turn_flags['guardian_round_focus'] == e.state.round_number
    assert any((v.event_type == 'RESOURCE_GAINED' and v.source_definition_id == FOCUS for v in e.events))

@pytest.mark.parametrize('case', ['save_success', 'unowned', 'legacy', 'expired', 'immune'])
def test_maneuver_requires_success_owned_new_row_and_active_patrol(tmp_path, case):

    def legacy(b):
        if case == 'legacy':
            for r in b['typed_passives']:
                r.pop('maneuver_focus', None)
    talents = [PATROL, SWIFT] + ([] if case == 'unowned' else [FOCUS])
    c, t, m = fight(tmp_path, talents, left_score=50, right_score=214 if case == 'save_success' else 14, left_kit={'items': []}, bundle_edit=legacy, prepare=[{'type': 'immunity', 'conditions': ['prone'], 'applies_to': 'target', 'duration': 'one_minute'}] if case == 'immune' else [])
    if case == 'immune':
        settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    settle(lambda a: act(t, m, LABEL, a))
    if case == 'expired':
        turn(t, m, RIGHT)
        turn(t, m, LEFT)
    settle(lambda a: act(t, m, 'Shove: Prone', a, target_id=RIGHT))
    assert reload(c, m).state.actors[LEFT].resources[RESOURCE] == 0

@pytest.mark.parametrize('case', ['near', 'reach', 'far', 'ended', 'unowned', 'legacy'])
def test_mageguard_qualifies_actual_concentration_save_by_challenge_and_reach(tmp_path, case):
    mage = 'TAL_GUARDIAN_MAGEGUARD'

    def legacy(b):
        if case == 'legacy':
            b['typed_passives'][:] = [r for r in b['typed_passives'] if r.get('kind') != 'mageguard']
    effects = [{'type': 'guardian_challenge', 'applies_to': 'target'}]
    if case == 'ended':
        effects.append({'type': 'remove_condition', 'condition': 'challenged', 'applies_to': 'target'})
    kit = {'items': [{'item_id': 'tianxia.mortal.weapon.ge', 'name': 'Ge (Dagger-Axe)', 'quantity': 1}]} if case == 'reach' else None
    c, t, m = fight(tmp_path, [mage] if case != 'unowned' else [], bundle_edit=legacy, left_kit=kit, right_score=214, right_talents=['tianxia.talent.poison.miasma_form'], prepare=effects, positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 7 if case == 'far' else 5 if case == 'reach' else 4, 'y': 6}}, cause_target='SELF', cause=[{'type': 'save', 'ability': 'con', 'dc': 'technique_save_dc', 'applies_to': 'self', 'on_fail': [], 'on_success': []}, {'type': 'damage', 'flat': 1, 'damage_types': ['fire'], 'applies_to': 'self'}])
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, 'Miasma Form', a))
    turn(t, m, LEFT)
    settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    turn(t, m, RIGHT)
    before = len(reload(c, m).events)
    settle(lambda a: act(t, m, 'Cause', a))
    e = reload(c, m)
    saves = [v for v in e.events[before:] if v.event_type == 'SAVE_ROLLED']
    assert [v.payload['mode'] for v in saves] == ['NORMAL', 'DISADVANTAGE' if case in {'near', 'reach'} else 'NORMAL']
    assert e.state.actors[RIGHT].concentration is not None
